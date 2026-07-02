(function () {
    var allowedPlaybackRates = [0.8, 1.0, 1.2, 1.5, 2.0];

    function getAudio() {
        return document.getElementById('remoteAudio');
    }

    function setText(id, value) {
        var element = document.getElementById(id);
        if (element) {
            element.textContent = value;
        }
    }

    function safeNumber(value, fallback) {
        var numberValue = Number(value);
        return Number.isFinite(numberValue) ? numberValue : fallback;
    }

    function normalizeSeconds(seconds) {
        var value = Number(seconds);
        return Number.isFinite(value) ? value : 0;
    }

    function getFileMeta(audio) {
        var file = window.KoeRadiFile || {};
        var dataset = audio ? audio.dataset : {};
        return {
            fileId: file.file_id || dataset.fileId || '',
            title: file.title || dataset.title || '',
            station: file.station || dataset.station || '',
            date: file.date || dataset.date || ''
        };
    }

    function getFiniteCurrentTime(audio) {
        if (!audio) {
            return 0;
        }
        var currentTime = Number(audio.currentTime);
        return Number.isFinite(currentTime) && currentTime > 0 ? currentTime : 0;
    }

    function getFiniteDuration(audio) {
        if (!audio) {
            return 0;
        }
        var duration = Number(audio.duration);
        return Number.isFinite(duration) && duration > 0 ? duration : 0;
    }

    function audioIsPlaying(audio) {
        return Boolean(audio && !audio.paused && !audio.ended);
    }

    function formatSeconds(seconds) {
        var value = Number(seconds);
        if (!Number.isFinite(value) || value < 0) {
            value = 0;
        }
        return value.toFixed(1) + 's';
    }

    function statusForEvent(type, state) {
        if (type === 'play') {
            return '再生中';
        }
        if (type === 'pause') {
            return '一時停止';
        }
        if (type === 'ended') {
            return '再生終了';
        }
        if (type === 'loadedmetadata') {
            return 'メタデータ読み込み完了';
        }
        if (type === 'timeupdate') {
            return state.playing ? '再生中' : '一時停止';
        }
        if (type === 'error') {
            return '再生エラー';
        }
        return state.playing ? '再生中' : '再生待機中';
    }

    function renderState(message, eventType) {
        var state = window.getPlaybackState();
        setText('remotePlaybackStatus', message || statusForEvent(eventType || 'state', state));
        setText('remoteCurrentTime', formatSeconds(state.currentTime));
        setText('remoteDuration', formatSeconds(state.duration));
        setText('remotePlaybackRate', String(state.playbackRate));
        setText('remoteLastEvent', eventType || (window.KoeRadiLastEvent && window.KoeRadiLastEvent.type) || 'init');
        setText('remotePlaybackState', JSON.stringify(state, null, 2));
        return state;
    }

    function recordAudioEvent(type) {
        var state = renderState(null, type);
        window.KoeRadiLastEvent = {
            type: type,
            state: state
        };
        setText('remoteLastEvent', type);
        setText('remotePlaybackState', JSON.stringify(state, null, 2));
        return window.KoeRadiLastEvent;
    }

    window.playAudio = function () {
        var audio = getAudio();
        if (!audio) {
            renderState('audioタグが見つかりません。');
            return false;
        }

        var result = audio.play();
        if (result && typeof result.catch === 'function') {
            result.catch(function (error) {
                var name = error && error.name ? error.name : 'play-error';
                renderState('再生待機中: ' + name);
            });
        }
        renderState('再生要求');
        return true;
    };

    window.pauseAudio = function () {
        var audio = getAudio();
        if (!audio) {
            return false;
        }

        audio.pause();
        renderState('一時停止');
        return true;
    };

    window.togglePlay = function () {
        var audio = getAudio();
        if (!audio) {
            return false;
        }
        return audioIsPlaying(audio) ? window.pauseAudio() : window.playAudio();
    };

    window.seekBy = function (seconds) {
        var audio = getAudio();
        if (!audio) {
            renderState('audioタグが見つかりません。');
            return false;
        }

        var delta = normalizeSeconds(seconds);
        var duration = getFiniteDuration(audio);
        var nextTime = getFiniteCurrentTime(audio) + delta;

        if (duration > 0) {
            nextTime = Math.min(duration, nextTime);
        }
        nextTime = Math.max(0, nextTime);

        try {
            audio.currentTime = nextTime;
        } catch (error) {
            renderState('シークできません。');
            return false;
        }

        renderState(delta >= 0 ? 'シークしました' : '戻しました');
        return getFiniteCurrentTime(audio);
    };

    window.seekForward = function (seconds) {
        return window.seekBy(Math.abs(normalizeSeconds(seconds)));
    };

    window.seekBackward = function (seconds) {
        return window.seekBy(-Math.abs(normalizeSeconds(seconds)));
    };

    window.setPlaybackRate = function (rate) {
        var audio = getAudio();
        var value = Number(rate);
        if (!audio) {
            return false;
        }

        if (!allowedPlaybackRates.some(function (allowedRate) {
            return Math.abs(allowedRate - value) < 0.001;
        })) {
            value = 1.0;
        }
        audio.playbackRate = value;
        renderState('再生速度: ' + audio.playbackRate);
        return audio.playbackRate;
    };

    window.getPlaybackState = function () {
        var audio = getAudio();
        var meta = getFileMeta(audio);
        return {
            playing: audioIsPlaying(audio),
            currentTime: getFiniteCurrentTime(audio),
            duration: getFiniteDuration(audio),
            playbackRate: audio ? safeNumber(audio.playbackRate, 1.0) : 1.0,
            fileId: meta.fileId,
            title: meta.title,
            station: meta.station,
            date: meta.date
        };
    };

    window.getCurrentTime = function () {
        return getFiniteCurrentTime(getAudio());
    };

    window.getDuration = function () {
        return getFiniteDuration(getAudio());
    };

    window.isPlaying = function () {
        return audioIsPlaying(getAudio());
    };

    function initializeRemotePlayer() {
        var audio = getAudio();
        if (!audio) {
            renderState();
            return;
        }

        renderState(audio.paused ? '再生待機中' : '再生中');
        ['play', 'pause', 'ended', 'loadedmetadata', 'timeupdate', 'error'].forEach(function (eventName) {
            audio.addEventListener(eventName, function () {
                recordAudioEvent(eventName);
            });
        });
    }

    initializeRemotePlayer();
}());
