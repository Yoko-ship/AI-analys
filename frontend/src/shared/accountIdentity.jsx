

function accountInitials(user) {
  const words = String(user?.full_name || "").trim().split(/\s+/).filter(Boolean);
  const letters = words.length ? words.slice(0, 2).map((word) => word[0]) : [String(user?.email || "?")[0]];
  return letters.join("").toUpperCase();
}

export { accountInitials };
