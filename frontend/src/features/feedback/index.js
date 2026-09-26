// Public interface for this feature.
import { lazy } from "react";
export const FeedbackPage = lazy(() => import("./FeedbackPage.jsx").then(module => ({ default: module.FeedbackPage })));
