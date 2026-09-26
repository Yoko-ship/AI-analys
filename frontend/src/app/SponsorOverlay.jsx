import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import promoVideo from "../assets/promo.mp4";
import promoPoster from "../assets/promo-poster.jpg";

// Floating sponsor unit. Its 2.6 MB video waits until the page's load event,
// so it cannot compete with the first market-page render on a slow connection.
//
// Rules it keeps, because an ad that breaks them is a bug: sound never starts
// on its own (browsers refuse it anyway, and it is rude); the close control
// always arrives, on a visible countdown; once dismissed or finished it stays
// gone for the rest of the session; and a reader who asked the OS for reduced
// motion gets the poster with a play button instead of a moving picture.
//
// The close countdown begins when the promotion appears, shortly after the
// page load event. A reader can also start the video manually at any point.
const SPONSOR_SEEN_KEY = "uz_sponsor_seen";

const SPONSOR_DELAY_MS = 2500;

// let the page settle before anything moves
const SPONSOR_CLOSE_AFTER = 15;

// seconds before the × replaces the countdown

function SponsorOverlay({ language }) {
  const [open, setOpen] = useState(false);
  const [muted, setMuted] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [left, setLeft] = useState(SPONSOR_CLOSE_AFTER);
  const [progress, setProgress] = useState(0);
  // Bumped by a click the countdown refused: it replays the pill's pulse, so a
  // click that does nothing still points at the reason it did nothing.
  const [nudge, setNudge] = useState(0);
  const videoRef = useRef(null);
  const reduced = typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // The mandatory window. Reduced motion is exempt: that reader was never given
  // a playing clip to stop, only the poster and a play button.
  const locked = open && !reduced && left > 0;

  useEffect(() => {
    try { if (sessionStorage.getItem(SPONSOR_SEEN_KEY)) return undefined; } catch (e) { /* ignore */ }
    let id = null;
    const showAfterLoad = () => { id = window.setTimeout(() => setOpen(true), SPONSOR_DELAY_MS); };
    if (document.readyState === "complete") showAfterLoad();
    else window.addEventListener("load", showAfterLoad, { once: true });
    return () => {
      if (id !== null) window.clearTimeout(id);
      window.removeEventListener("load", showAfterLoad);
    };
  }, []);

  const dismiss = () => {
    setOpen(false);
    try { sessionStorage.setItem(SPONSOR_SEEN_KEY, "1"); } catch (e) { /* ignore */ }
  };

  // Start muted only after the document has completed loading and the player
  // is allowed to appear. If a browser refuses autoplay, keep the play button.
  useEffect(() => {
    if (!open || reduced) return;
    const v = videoRef.current;
    if (!v) return;
    v.muted = true;
    v.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, [open, reduced]);

  // The countdown runs on the wall clock once the promotion is visible.
  useEffect(() => {
    if (!open) return undefined;
    setLeft(SPONSOR_CLOSE_AFTER);
    const id = setInterval(() => setLeft((n) => (n <= 1 ? 0 : n - 1)), 1000);
    return () => clearInterval(id);
  }, [open]);

  // Our own click handler is not the only way to stop a video: OS media keys,
  // the picture-in-picture window and a phone's app switcher all pause it. While
  // the countdown runs the unit puts itself back — the guard lives on the `pause`
  // event, so it holds whatever route the pause arrived by.
  useEffect(() => {
    if (!locked) return undefined;
    const v = videoRef.current;
    if (!v) return undefined;
    const resume = () => {
      // The pause that closes a clip is it finishing, not a viewer stopping it.
      if (v.ended || (v.duration && v.currentTime >= v.duration - 0.25)) return;
      // If the browser refuses (a data-saver mode, a backgrounded tab), show the
      // ▶ again rather than leaving a still frame nobody can restart.
      v.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    };
    // Coming back to a backgrounded tab: the browser paused it there and does not
    // resume on its own, which would otherwise hand back a way to sit out the
    // window with the clip stopped.
    const onVisible = () => { if (!document.hidden && v.paused) resume(); };
    v.addEventListener("pause", resume);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      v.removeEventListener("pause", resume);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [locked]);

  if (!open) return null;

  const label = language === "en" ? "Advertisement" : language === "uz" ? "Reklama" : "Реклама";
  const closeLabel = language === "en" ? "Close" : language === "uz" ? "Yopish" : "Закрыть";
  const soundLabel = muted
    ? (language === "en" ? "Sound on" : language === "uz" ? "Ovozni yoqish" : "Включить звук")
    : (language === "en" ? "Sound off" : language === "uz" ? "Ovozni o'chirish" : "Выключить звук");

  const toggleSound = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
    if (!v.muted && v.paused) v.play().then(() => setPlaying(true)).catch(() => {});
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    // Starting it is always allowed — it is the stopping that the countdown
    // withholds, and a clip whose autoplay was refused still needs a way in.
    if (v.paused) { v.play().then(() => setPlaying(true)).catch(() => {}); return; }
    if (locked) { setNudge((n) => n + 1); return; }
    v.pause();
    setPlaying(false);
  };

  return createPortal(
    <aside className="sponsor-overlay" role="complementary" aria-label={label}>
      <div className="sponsor-overlay-frame">
        <video
          ref={videoRef}
          src={promoVideo}
          poster={promoPoster}
          muted={muted}
          playsInline
          preload="none"
          className={locked && playing ? "is-locked" : undefined}
          onClick={togglePlay}
          onTimeUpdate={(e) => {
            const v = e.currentTarget;
            if (v.duration) setProgress((v.currentTime / v.duration) * 100);
          }}
          onEnded={dismiss}
        />

        <button type="button" className="sponsor-overlay-sound" onClick={toggleSound} title={soundLabel} aria-label={soundLabel}>
          {muted ? "🔇" : "🔊"}
        </button>

        {left > 0 ? (
          /* Keyed on the nudge counter so a refused click remounts the pill and
             replays its pulse — a CSS animation does not restart on a class that
             is already there. */
          <span key={nudge} className={`sponsor-overlay-count${nudge ? " is-nudged" : ""}`} aria-hidden="true">{left}</span>
        ) : (
          <button type="button" className="sponsor-overlay-close" onClick={dismiss} title={closeLabel} aria-label={closeLabel}>×</button>
        )}

        {!playing && (
          <button type="button" className="sponsor-overlay-play" onClick={togglePlay} aria-label={closeLabel === "Close" ? "Play" : "Смотреть"}>▶</button>
        )}

        <span className="sponsor-overlay-label">{label}</span>
        <div className="sponsor-overlay-bar"><i style={{ width: `${progress}%` }} /></div>
      </div>
    </aside>,
    document.body
  );
}

export { SponsorOverlay };
