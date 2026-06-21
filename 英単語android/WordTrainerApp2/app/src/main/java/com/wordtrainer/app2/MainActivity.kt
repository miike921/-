package com.wordtrainer.app2

import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.webkit.*
import androidx.appcompat.app.AppCompatActivity
import java.util.Locale

class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {

    private lateinit var webView: WebView
    private lateinit var tts: TextToSpeech
    private var ttsReady = false

    inner class TTSBridge {
        @JavascriptInterface
        fun speak(text: String, lang: String, rate: Double) {
            if (!ttsReady) {
                runOnUiThread {
                    webView.evaluateJavascript("window.__ttsOnEnd&&window.__ttsOnEnd()", null)
                }
                return
            }
            val locale = if (lang.startsWith("ja")) Locale.JAPAN else Locale.US
            tts.language = locale
            tts.setSpeechRate(rate.toFloat())
            tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "u1")
        }

        @JavascriptInterface
        fun stop() {
            if (ttsReady) tts.stop()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tts = TextToSpeech(this, this)
        webView = findViewById(R.id.webView)

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                injectTTSBridge(view)
            }
        }
        webView.webChromeClient = WebChromeClient()

        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            mediaPlaybackRequiresUserGesture = false
        }

        webView.addJavascriptInterface(TTSBridge(), "AndroidTTS")
        webView.loadUrl("file:///android_asset/word_trainer.html")
    }

    private fun injectTTSBridge(view: WebView?) {
        val js = """
            (function() {
                window.__ttsOnEnd = null;
                window.speechSynthesis = {
                    speak: function(u) {
                        window.__ttsOnEnd = function() {
                            window.__ttsOnEnd = null;
                            if (u.onend) setTimeout(function(){ u.onend(); }, 50);
                        };
                        AndroidTTS.speak(u.text || '', u.lang || 'en-US', u.rate || 1.0);
                    },
                    cancel: function() {
                        window.__ttsOnEnd = null;
                        AndroidTTS.stop();
                    },
                    getVoices: function() { return []; },
                    onvoiceschanged: null,
                    speaking: false,
                    pending: false
                };
                window.SpeechSynthesisUtterance = function(text) {
                    this.text = text || '';
                    this.lang = 'en-US';
                    this.rate = 1.0;
                    this.volume = 1.0;
                    this.onend = null;
                    this.onerror = null;
                };
            })();
        """.trimIndent()
        view?.evaluateJavascript(js, null)
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            ttsReady = true
            tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) {}
                override fun onDone(utteranceId: String?) {
                    runOnUiThread {
                        webView.evaluateJavascript("window.__ttsOnEnd&&window.__ttsOnEnd()", null)
                    }
                }
                @Deprecated("Deprecated")
                override fun onError(utteranceId: String?) {
                    runOnUiThread {
                        webView.evaluateJavascript("window.__ttsOnEnd&&window.__ttsOnEnd()", null)
                    }
                }
            })
        }
    }

    override fun onDestroy() {
        tts.stop()
        tts.shutdown()
        super.onDestroy()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }
}
