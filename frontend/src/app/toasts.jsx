import { t } from "../shared/i18n.jsx";

function ToastStack({ toasts, onDismiss, language }) {
  return (
    <div className="toast-stack" aria-live="polite" aria-atomic="true">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.tone} show`}>
          <div className="toast-label">{toast.tone === "error" ? t(language, "toasts.error") : toast.tone === "success" ? t(language, "toasts.success") : t(language, "toasts.info")}</div>
          <div className="toast-message">{toast.message}</div>
          <button className="toast-close" type="button" onClick={() => onDismiss(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

export { ToastStack };
