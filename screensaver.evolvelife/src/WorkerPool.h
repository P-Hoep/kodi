// A tiny fork-join pool: Run(n, fn) calls fn(begin, end) over [0, n) split
// into one contiguous slice per thread, the calling thread taking the first
// slice, and returns when every slice is done. Workers sleep on a condition
// variable between jobs, so an idle pool costs nothing.
#pragma once

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

#if defined(__APPLE__)
#include <pthread.h>
#include <sys/qos.h>
#elif defined(__linux__) || defined(__ANDROID__)
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

namespace evo
{

// Below-normal priority for the calling thread: evolution never competes
// with Kodi's render thread for a core.
inline void LowerThreadPriority()
{
#if defined(__APPLE__)
  pthread_set_qos_class_self_np(QOS_CLASS_UTILITY, 0);
#elif defined(__linux__) || defined(__ANDROID__)
  setpriority(PRIO_PROCESS, static_cast<id_t>(syscall(SYS_gettid)), 10);
#endif
}

class WorkerPool
{
public:
  WorkerPool() = default;
  WorkerPool(const WorkerPool&) = delete;
  WorkerPool& operator=(const WorkerPool&) = delete;
  ~WorkerPool() { Stop(); }

  // `threads` is the total including the caller; 0 = one per core, up to 4
  // (the neighbour loop is memory-bound well before that).
  // background: run the workers at a low priority, below Kodi's threads
  void Start(int threads, bool background = false)
  {
    m_background = background;
    Stop();
    if (threads <= 0)
    {
      const unsigned hw = std::thread::hardware_concurrency();
      threads = static_cast<int>(std::min(hw ? hw : 1u, 4u));
    }
    m_total = std::max(1, threads);
    m_quit = false;
    m_generation = 0;
    for (int i = 1; i < m_total; i++)
      m_workers.emplace_back([this, i] { Loop(i); });
  }

  void Stop()
  {
    {
      std::lock_guard<std::mutex> lock(m_mutex);
      m_quit = true;
    }
    m_wake.notify_all();
    for (auto& t : m_workers)
      if (t.joinable())
        t.join();
    m_workers.clear();
    m_total = 1;
  }

  int threads() const { return m_total; }

  // fn(i) for every i in [0, n), handed out one at a time to whichever thread
  // is free: for jobs of uneven cost (a creature that gives up early).
  void RunEach(size_t n, const std::function<void(size_t)>& fn)
  {
    if (m_total <= 1 || n < 2)
    {
      for (size_t i = 0; i < n; i++)
        fn(i);
      return;
    }
    std::atomic<size_t> next{0};
    Run(2 * static_cast<size_t>(m_total), [&](size_t, size_t) {
      for (;;)
      {
        const size_t i = next.fetch_add(1);
        if (i >= n)
          return;
        fn(i);
      }
    });
  }

  void Run(size_t n, const std::function<void(size_t, size_t)>& fn)
  {
    if (m_total <= 1 || n < 2 * static_cast<size_t>(m_total))
    {
      fn(0, n);
      return;
    }
    {
      std::lock_guard<std::mutex> lock(m_mutex);
      m_job = &fn;
      m_n = n;
      m_pending = m_total - 1;
      m_generation++;
    }
    m_wake.notify_all();
    fn(0, SliceEnd(0));
    std::unique_lock<std::mutex> lock(m_mutex);
    m_done.wait(lock, [this] { return m_pending == 0; });
    m_job = nullptr;
  }

private:
  size_t SliceEnd(int i) const { return m_n * static_cast<size_t>(i + 1) / m_total; }

  void Loop(int index)
  {
    if (m_background)
      LowerThreadPriority();
    unsigned seen = 0;
    for (;;)
    {
      const std::function<void(size_t, size_t)>* job;
      {
        std::unique_lock<std::mutex> lock(m_mutex);
        m_wake.wait(lock, [&] { return m_quit || m_generation != seen; });
        if (m_quit)
          return;
        seen = m_generation;
        job = m_job;
      }
      (*job)(SliceEnd(index - 1), SliceEnd(index));
      {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (--m_pending == 0)
          m_done.notify_one();
      }
    }
  }

  std::vector<std::thread> m_workers;
  std::mutex m_mutex;
  std::condition_variable m_wake, m_done;
  const std::function<void(size_t, size_t)>* m_job = nullptr;
  size_t m_n = 0;
  int m_pending = 0;
  int m_total = 1;
  unsigned m_generation = 0;
  bool m_quit = false;
  bool m_background = false;
};

} // namespace evo
