import React from "react";
import ReactDOM from "react-dom/client";
import ChatApp from "./ChatApp.jsx";
import "./styles.css";
import "./theme.css";
import "./chat.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ChatApp />
  </React.StrictMode>
);
