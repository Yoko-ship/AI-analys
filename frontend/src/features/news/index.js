// Public interface for this feature.
import { lazy } from "react";
export const NewsView = lazy(() => import("./NewsView.jsx").then(module => ({
  default: module.NewsView
})));
export const NewsArticleView = lazy(() => import("./NewsArticleView.jsx").then(module => ({
  default: module.NewsArticleView
})));
export const AnnouncementArticleView = lazy(() => import("./AnnouncementArticleView.jsx").then(module => ({
  default: module.AnnouncementArticleView
})));
export { EDNEWS_TX, edHeadline, interceptNav, newsArticlePath, newsRelTime } from "./editorial.jsx";
