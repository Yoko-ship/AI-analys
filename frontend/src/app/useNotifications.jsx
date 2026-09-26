import { useEffect, useState } from "react";

export function useNotifications({ session: sessionModule, toasts: toastsModule, navigation: navigationModule }) {
  const { user, token, profile, apiFetch } = sessionModule;
  const { addToast } = toastsModule;
  const { setAdminSection, setActiveView, openCompanyPage } = navigationModule;
  const [notifCount, setNotifCount] = useState(0);

  const [notifItems, setNotifItems] = useState([]);

  const [notifOpen, setNotifOpen] = useState(false);

  useEffect(() => {
    const isAdmin = Boolean(user?.is_admin || user?.admin_role === "administrator");
    if (!token || (!Boolean(profile?.user?.pro_access ?? user?.pro_access) && !isAdmin)) { setNotifCount(0); setNotifItems([]); return; }
    const fetchNotifs = () => {
      apiFetch("/api/notifications")
        .then((r) => r.json())
        .then((d) => { if (d.ok) { setNotifCount(d.count || 0); setNotifItems(d.items || []); } })
        .catch(() => {});
    };
    fetchNotifs();
    // Feedback is an operational inbox: administrators should see a new
    // message promptly, while investment alerts keep their lighter cadence.
    const id = setInterval(fetchNotifs, isAdmin ? 60 * 1000 : 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [token, profile?.user?.pro_access, user?.pro_access, user?.is_admin, user?.admin_role, apiFetch]);

  const updateNotificationState = async (ids, dismissed = false) => {
    const cleanIds = (ids || []).filter(Boolean);
    if (!cleanIds.length) return;
    try {
      const res = await apiFetch(`/api/notifications/${dismissed ? "clear" : "read"}`, {
        method: "POST",
        body: JSON.stringify({ ids: cleanIds }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not update notifications");
      if (dismissed) setNotifItems((items) => items.filter((item) => !cleanIds.includes(item.id)));
      else setNotifItems((items) => items.map((item) => cleanIds.includes(item.id) ? { ...item, read: true } : item));
      setNotifCount((count) => Math.max(0, count - cleanIds.filter((id) => notifItems.some((item) => item.id === id && !item.read)).length));
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const openNotification = (notification) => {
    updateNotificationState([notification.id]);
    setNotifOpen(false);
    if (notification.kind === "feedback" && (user?.is_admin || user?.admin_role === "administrator")) {
      setAdminSection("feedback");
      setActiveView("admin");
    }
    if (notification.kind === "pattern" && notification.ticker) openCompanyPage(notification.ticker);
  };
  return { notifCount, notifItems, notifOpen, openNotification, setNotifOpen, updateNotificationState };
}
