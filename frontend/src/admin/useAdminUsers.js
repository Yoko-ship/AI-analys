import { useCallback, useState } from "react";
export function useAdminUsers({
  readJson,
  alive,
  setBusy,
  setError
}) {
  const [usersData, setUsersData] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [adminLog, setAdminLog] = useState(null);
  const [usersQuery, setUsersQuery] = useState("");
  const [usersOnly, setUsersOnly] = useState("");
  const [userDetail, setUserDetail] = useState(null);
  const [confirmAction, setConfirmAction] = useState(null);
  const loadUsers = useCallback(async (query, only) => {
    const params = new URLSearchParams({
      limit: "100"
    });
    if (query) params.set("query", query);
    if (only) params.set("only", only);
    const [list, fun, log] = await Promise.all([readJson(`/api/admin/users?${params}`), readJson("/api/admin/users/funnel?days=30"), readJson("/api/admin/audit-log?limit=30")]);
    if (alive.current) {
      setUsersData(list);
      setFunnel(fun);
      setAdminLog(log);
    }
  }, [readJson, alive]);
  const openUser = useCallback(async id => {
    const data = await readJson(`/api/admin/users/${id}`);
    if (alive.current) setUserDetail(data);
  }, [readJson, alive]);
  const runUserAction = useCallback(async (id, action) => {
    setBusy(true);
    setError("");
    try {
      await readJson(`/api/admin/users/${id}/action`, {
        method: "POST",
        body: JSON.stringify(action === "delete" ? {
          action,
          confirm: true
        } : {
          action
        })
      });
      setConfirmAction(null);
      if (action === "delete") setUserDetail(null);else if (userDetail && userDetail.user && userDetail.user.id === id) await openUser(id);
      await loadUsers(usersQuery, usersOnly);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [readJson, loadUsers, openUser, usersQuery, usersOnly, userDetail, setBusy, setError, alive]);
  return {
    usersData,
    funnel,
    adminLog,
    usersQuery,
    setUsersQuery,
    usersOnly,
    setUsersOnly,
    userDetail,
    setUserDetail,
    confirmAction,
    setConfirmAction,
    loadUsers,
    openUser,
    runUserAction
  };
}
