

const LANGUAGE_KEY = "uz_stock_analyzer_language";

const THEME_KEY = "uz_stock_analyzer_theme";

const TEXT_SCALE_KEY = "uz_text_scale";

// Text size, as a percentage of the design's own. Five steps: two down for a
// reader on a small laptop who wants more rows in view, two up for one who is
// reading a table of figures at arm's length.
//
// Applied as `zoom` on the root element, not as a root font-size. This stylesheet
// states most of its sizes in PIXELS — a table of numbers is laid out against
// tabular figures and hairline borders, and eleven thousand lines of it cannot be
// converted to rem without redesigning every table on the site. Root zoom scales
// what the reader actually sees (text, controls, the gaps between rows) uniformly
// and consistently, including the popovers that portal to <body>, and the browser
// evaluates media queries against the scaled viewport — so at 140 % the phone
// layout arrives early, which is the right answer for a reader who has asked for
// bigger text.
const TEXT_SCALES = [85, 100, 115, 130, 150];

export { LANGUAGE_KEY, TEXT_SCALES, TEXT_SCALE_KEY, THEME_KEY };
