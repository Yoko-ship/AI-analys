import { lazy } from "react";

const ProfileAccountCenter = lazy(() => import("../../ProfileAccountCenter.jsx").then((module) => ({ default: module.ProfileAccountCenter })));

const ProfileFavoriteEditor = lazy(() => import("../../ProfileAccountCenter.jsx").then((module) => ({ default: module.ProfileFavoriteEditor })));

const ProfileNoteEditor = lazy(() => import("../../ProfileAccountCenter.jsx").then((module) => ({ default: module.ProfileNoteEditor })));

export { ProfileAccountCenter, ProfileFavoriteEditor, ProfileNoteEditor };
