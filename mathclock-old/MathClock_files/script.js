function initializePage() {

    var secondsParam = getUrlParameter('seconds');
    var militaryTime = getUrlParameter('militaryTime');
    var inverted = getUrlParameter('inverted');
    var dateParam = getUrlParameter('date');
    var labelParam = getUrlParameter('labels');
    var dayNightMode = getUrlParameter('dayNight');

    if (militaryTime) {
        $('#militaryCheck').attr('checked', 'checked');
        $('#military').removeClass('hidden');
    }

    if (labelParam) {
        $('#labelCheck').attr('checked', 'checked');
        $('.timeLabel').removeClass('hidden');
    }

    if (secondsParam) {
        $('#secondCheck').attr('checked', 'checked');
    }
    else {
        $('.secondToggle').addClass('hidden');
    }

    if (inverted) {
        $('#invertedCheck').attr('checked', 'checked');
        $('body').addClass('inverted');
    }

    if (dayNightMode) {
        $('#dayNightCheck').attr('checked', 'checked');
    }

    if (dateParam) {
        $('#dateCheck').attr('checked', 'checked');
    }
    else {
        $('.dateToggle').addClass('hidden');
    }


    function getRandomInt(max) {
        return Math.floor(Math.random() * max) + 1;
    }

    var now = new Date();
    var hour = (militaryTime) ? now.getHours() : ((now.getHours() + 11) % 12 + 1);
    var minute = now.getMinutes();
    var month = now.getMonth() + 1;
    var day = now.getDate();
    var year = now.getFullYear();

    function getHours() {
        return (militaryTime) ? now.getHours() : ((now.getHours() + 11) % 12 + 1);
    }

    function get24Hours() {
        return now.getHours();
    }

    function getMinutes() {
        return now.getMinutes();
    }

    function getSeconds() {
        return now.getSeconds();
    }

    function getMonth() {
        return now.getMonth() + 1;
    }

    function getDay() {
        return now.getDate();
    }

    function getYear() {
        return now.getFullYear();
    }

    function getHourVariable() {
        return 'h';
    }

    function getMinuteVariable() {
        return 'm';
    }

    function getSecondVariable() {
        return 's';
    }

    function getMonthVariable() {
        return 'm'
    }

    function getYearVariable() {
        return 'y'
    }

    function getDayVariable() {
        return 'd'
    }

    var array_of_functions = [

        function (value, variableName) {
            var randomSubtract = getRandomInt(25);
            var answerSubtract = value - randomSubtract;
            return "\\(" + variableName + " - " + randomSubtract + " = " + answerSubtract + "\\)";
        },

        function (value, variableName) {
            var randomSubtract = getRandomInt(25);
            var answerSubtract = randomSubtract - value;
            return "\\(" + randomSubtract + " - " + variableName + " = " + answerSubtract + "\\)";
        },

        function (value, variableName) {
            var randomSubtract = getRandomInt(25);
            var answerSubtract = value + randomSubtract;
            return "\\(" + variableName + " + " + randomSubtract + " = " + answerSubtract + "\\)";
        },

        function (value, variableName) {
            var randomSubtract = getRandomInt(25);
            var answerSubtract = value + randomSubtract;
            return "\\(" + randomSubtract + " + " + variableName + " = " + answerSubtract + "\\)";
        },

        function (value, variableName) {
            var randomMultiply = getRandomInt(5);
            return "\\(" + variableName + "  {\\times}   " + randomMultiply + " = " + (value * randomMultiply) + "\\)";

        },

        function (value, variableName) {
            var randomMultiply = getRandomInt(5);
            var divisor = randomMultiply * value
            return "\\(" + divisor + "  {\\div}  " + randomMultiply + " = " + variableName + "\\)";

        },

        function (value) {
            var randomAdd = getRandomInt(20);
            return "\\(" + (value - randomAdd) + " + " + randomAdd + "\\)";
        },

        function (value) {
            var randomAdd = getRandomInt(20);
            return "\\(" + (value + randomAdd) + " - " + randomAdd + "\\)";
        },

        function (value) {
            var randomAdd = getRandomInt(20);
            var randomSubtract = getRandomInt(20);
            return "\\(" + (value + randomSubtract - randomAdd) + " - " + randomSubtract + " + " + randomAdd + "\\)";
        },

        function (value) {
            var randomAdd = getRandomInt(20);
            return "\\(" + (value + randomAdd) + " - " + randomAdd + "\\)";
        },

        function (value, variable) {
            var double = value * value;
            return "$${\\sqrt{" + double + "}}$$"
        },

        function (value, variable) {

            if (Math.sqrt(value) % 1 === 0) {
                return '$$' + Math.sqrt(value) + '^2$$'
            }
            else {
                return array_of_functions[getRandomInt(array_of_functions.length) - 1](value, variable);
            }
        },

        // This is easy, the answer is just the number in the square root
        function (value, variable) {
            return "$${\\sqrt{" + value + "}}\\times{\\sqrt{" + value + "}}$$"
        },

        function (value, variable) {

            if (value % 2 === 1) {
                return '$$(' + ((value - 1) / 2) + '{\\times} 2) + 1$$'
            }
            else {
                return array_of_functions[getRandomInt(array_of_functions.length) - 1](value, variable);
            }
        },

        function (value, variable) {
            try {
            if (Math.cbrt(value) % 1 === 0) {
                return '$$' + Math.cbrt(value) + '^3$$'
            }
            else {
                return array_of_functions[getRandomInt(array_of_functions.length) - 1](value, variable);
            }
            }
            catch (ex)
            {
                return array_of_functions[getRandomInt(array_of_functions.length) - 1](value, variable);
            }
        },

        // factorials
        function (value, variable) {

            if (value === 1 || value === 2 || value === 6 || value === 24) {
                if (value === 1) {
                    return '$$' + value + '!$$';
                }
                if (value === 2) {
                    return '$$' + value + '!$$';
                }
                if (value === 6) {
                    return '$$3!$$';
                }
                if (value === 24) {
                    return '$$4!$$';
                }
            }
            else {
                return array_of_functions[getRandomInt(array_of_functions.length) - 1](value, variable);
            }
        },

        // modulo
        function (value, variable) {

            return '$$' + ((value * 2) + 1) + ' \\% ' + (value + 1) + '$$';
        },

        // modulo

        // function (value, variable) {
        //     var double = value * value;
        //     return "$$\\overline{)12345}$$"
        // },


        /* this is a multiline commen
        what
        the hell
        */

        // function (value, variable) {
        //     var randomMultiplicate = getRandomInt(10);
        //     var sum = value * randomMultiplicate;
        //     var challenge = sum - value;
        //     return " $$\\begin{array}{r}&" + sum + "\\\\-\\!\\!\\!\\!\\!\\!&" + challenge + "\\\\\\hline\\end{array}$$";
        // },
    ]

    var interval = (secondsParam) ? 1000 : 30000;

    $(document).ready(function () {

        $('.form-check-input').change(function () {
            setQueryStringandRefresh();
        })

        $("#HourMathDisplay").append("<p class='currentHour'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getHours(), getHourVariable()) + "</p>");
        $("#MinuteMathDisplay").append("<p class='currentMinute'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getMinutes(), getMinuteVariable()) + "</p>");
        if (secondsParam) {
            $("#SecondMathDisplay").append("<p class='currentSecond'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getSeconds(), getSecondVariable()) + "</p>");
        }
        if (dateParam) {
            $("#MonthMathDisplay").append("<p class='currentMonth'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getMonth(), getMonthVariable()) + "</p>");
            $("#DayMathDisplay").append("<p class='currentDay'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getDay(), getDayVariable()) + "</p>");
            $("#YearMathDisplay").append("<p class='currentYear'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getYear(), getYearVariable()) + "</p>");
        }
    });

    setInterval(function () {

        if (dayNightMode) {
            var currentHour = now.getHours();
            if (currentHour >= 8 && currentHour <= 16) {
                $('body').removeClass('inverted');
            }
            else {
                $('body').addClass('inverted');
            }
        }
        var newMinute = (getMinutes() !== minute);

        if (newMinute) {
            minute = getMinutes();
            $("#MinuteMathDisplay").append("<p class='hiddenMinute'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](minute, getMinuteVariable()) + "</p>");
            $("#HourMathDisplay").append("<p class='hiddenHour'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getHours(), getHourVariable()) + "</p>");
            if (dateParam) {
                $("#MonthMathDisplay").append("<p class='hiddenMonth'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getMonth(), getMonthVariable()) + "</p>");
                $("#DayMathDisplay").append("<p class='hiddenDay'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getDay(), getDayVariable()) + "</p>");
                $("#YearMathDisplay").append("<p class='hiddenYear'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getYear(), getYearVariable()) + "</p>");
            }
        }

        if (secondsParam) {
            $("#SecondMathDisplay").append("<p class='hiddenSecond'>" + array_of_functions[getRandomInt(array_of_functions.length) - 1](getSeconds(), getSecondVariable()) + "</p>");
        }

        MathJax.Hub.Config({
            messageStyle: "none"
        });

        MathJax.Hub.Queue(["Typeset", MathJax.Hub]);
        MathJax.Hub.Queue(function () {
            if (secondsParam) {
                $(".currentSecond").remove();
                $(".hiddenSecond").removeClass("hiddenSecond").addClass('currentSecond');
            }
            if (newMinute) {
                $(".currentMinute").remove();
                $(".hiddenMinute").removeClass("hiddenMinute").addClass('currentMinute');
                $(".currentHour").remove();
                $(".hiddenHour").removeClass("hiddenHour").addClass('currentHour');
                if (dateParam) {
                    $(".currentMonth").remove();
                    $(".currentDay").remove();
                    $(".currentYear").remove();
                    $(".hiddenMonth").removeClass("hiddenMonth").addClass('currentMonth');
                    $(".hiddenDay").removeClass("hiddenDay").addClass('currentDay');
                    $(".hiddenYear").removeClass("hiddenYear").addClass('currentYear');

                }
            }
        });
        now = new Date();
    }, interval);

    function getEquation() {

    }

    function setOptions() {

    }

    function getUrlParameter(name) {
        name = name.replace(/[\[]/, '\\[').replace(/[\]]/, '\\]');
        var regex = new RegExp('[\\?&]' + name + '=([^&#]*)');
        var results = regex.exec(location.search);
        return results === null ? '' : decodeURIComponent(results[1].replace(/\+/g, ' '));
    };

    function setQueryStringandRefresh() {


        var url = window.location.href;
        var a = url.indexOf("?");
        var b = url.substring(a);
        var c = url.replace(b, "");
        url = c;

        var options = $('.form-check-input:checked');

        for (i = 0; i < options.length; i++) {
            url = URL_add_parameter(url, $(options[i]).val(), 'true');
        }

        window.location = url;
    }

    function URL_add_parameter(url, param, value) {
        var hash = {};
        var parser = document.createElement('a');

        parser.href = url;

        var parameters = parser.search.split(/\?|&/);

        for (var i = 0; i < parameters.length; i++) {
            if (!parameters[i])
                continue;

            var ary = parameters[i].split('=');
            hash[ary[0]] = ary[1];
        }

        hash[param] = value;

        var list = [];
        Object.keys(hash).forEach(function (key) {
            list.push(key + '=' + hash[key]);
        });

        parser.search = '?' + list.join('&');
        return parser.href;
    }
}