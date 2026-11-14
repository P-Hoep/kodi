// A tiny fork-join pool: Run(n, fn) calls fn(begin, end) over [0, n) split
// into one contiguous slice per thread, the calling thread taking the first
// slice, and returns when every slice is done. Workers sleep on a condition
// variable between jobs, so an idle pool costs nothing.
#pragma once

#include <algorithm>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

namespace boids
{

class WorkerPool
{
public:
  WorkerPool() = default;
  WorkerPool(const WorkerPool&) = delete;
  WorkerPool& operator=(const WorkerPool&) = delete;
  ~WorkerPool() { Stop(); }

  // `threads` is the total including the caller; 0 = one per core, up to 4
  // (the neighbour loop is memory-bound well before that).
  void Start(int threads)
  {
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
};

} // namespace boids
