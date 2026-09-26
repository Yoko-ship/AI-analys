import { useState } from "react";

export function useToasts() {

  const [toasts, setToasts] = useState([]);

  const addToast = (message, tone = "info") => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 3600);
  };
  return { addToast, setToasts, toasts };
}
