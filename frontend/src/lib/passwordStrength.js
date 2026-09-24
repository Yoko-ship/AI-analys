// Client mirror of password_policy.py: the same refusal reasons, explained
// while the reader types. The server remains the authority — it checks the
// full ~100k common-password list; this file carries the 400 most common
// (UK NCSC list via SecLists, MIT) plus local words, enough for the meter.

const MIN_LENGTH = 8;
const MAX_LENGTH = 128;
const SITE_WORDS = ["uzstock", "uz stock", "uz-stock"];
const KEYBOARD_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm", "йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю"];
const LEET = { "@": "a", "4": "a", "3": "e", "0": "o", "$": "s", "5": "s", "1": "i", "!": "i", "7": "t" };
const COMMON = new Set(["!ab#cd$", "!~!1", "$hex", "0000", "000000", "00000000", "0000000000", "010203", "0123456", "0123456789", "0987654321", "101010", "102030", "1111", "11111", "111111", "1111111", "11111111", "1111111111", "111222", "111222tianya", "112233", "11223344", "121212", "123123", "123123123", "123321", "1234", "12341234", "12344321", "12345", "1234554321", "123456", "1234561", "1234567", "12345678", "123456789", "1234567890", "1234567891", "12345678910", "123456789a", "1234567a", "123456a", "123456q", "12345a", "12345q", "12345qwert", "1234qwer", "123654", "123654789", "123789", "123abc", "123qwe", "123qweasd", "12413", "12qwaszx", "131313", "1342", "147258", "147258369", "147852", "147852369", "159357", "159753", "1g2w3e4r", "1q2w3e", "1q2w3e4r", "1q2w3e4r5t", "1qaz2wsx", "1qaz2wsx3edc", "1qazxsw2", "212121", "222222", "232323", "252525", "290966", "29rsavoy", "333333", "3rjs1la7qe", "444444", "456123", "456789", "50cent", "5201314", "55555", "555555", "654321", "666666", "696969", "777777", "7777777", "789456", "789456123", "87654321", "888888", "88888888", "987654", "987654321", "999999", "a12345", "a123456", "a123456789", "aaaaaa", "abc123", "abcd1234", "abcdef", "abcdefg", "adidas", "alexander", "alexis", "allah", "amanda", "amanda1", "america", "andrea", "andrew", "andrew1", "angel", "angel1", "angela", "angels", "anthony", "anthony1", "antonio", "apple", "arsenal", "asd123", "asdasd", "asdasd5", "asdf", "asdf1234", "asdfasdf", "asdfgh", "asdfghjkl", "ashley", "ashley1", "assalom", "asshole", "asshole1", "austin", "azerty", "babygirl", "babygirl1", "bailey", "banana", "bandit", "barcelona", "baseball", "baseball1", "basketball", "batman", "benjamin", "bitch1", "blink182", "brandon", "brandon1", "bubbles", "buddy1", "buster", "butterfly", "butterfly1", "carlos", "charlie", "charlie1", "cheese", "chelsea", "chelsea1", "chicken", "chicken1", "chocolate", "chocolate1", "chris1", "christian", "cjmasterinf", "computer", "computer1", "cookie", "cookie1", "daniel", "daniel1", "danielle", "destiny", "diamond", "diosesfiel", "dpbk1234", "dragon", "dragon1", "elizabeth", "eminem", "family", "ferrari", "flower", "football", "football1", "forever", "fqrg7cs493", "freedom", "friends", "fuckoff", "fuckyou", "fuckyou1", "fuckyou2", "fuk19600", "gabriel", "george", "gfhjkm", "ghbdtn", "ginger", "golfer", "google", "gwerty", "gwerty123", "hannah", "hannah1", "happy1", "harley", "hello", "hello1", "hello123", "hockey", "homelesspa", "hottie1", "hunter", "hunter1", "iloveu", "iloveyou", "iloveyou1", "iloveyou2", "internet", "j38ifubn", "jackson", "james1", "jasmine", "jasmine1", "jennifer", "jessica", "jessica1", "jesus", "jesus1", "jonathan", "jordan", "jordan1", "jordan23", "joseph", "joshua", "junior", "justin", "justin1", "juventus", "killer", "killer1", "lauren", "letmein", "linkedin", "liverpool", "liverpool1", "lol123", "london", "love", "love12", "love123", "lovely", "loveme", "loveme1", "lovers", "loveyou", "lucky1", "madison", "maggie", "marina", "martin", "master", "matrix", "matthew", "matthew1", "melissa", "mercedes", "metallica", "michael", "michael1", "michelle", "michelle1", "mickey", "mommy1", "money1", "monkey", "monkey1", "monster", "morgan", "mother", "mustang", "mylove", "myspace", "myspace1", "naruto", "natasha", "nathan", "nicholas", "nicole", "nicole1", "nikita", "nirvana", "null", "number1", "oliver", "orange", "ozbekiston", "pakistan", "parol", "parola", "parolim", "passer2009", "passw0rd", "password", "password1", "password12", "password2", "patrick", "pe#5gz29ptzmse", "peanut", "pepper", "pokemon", "pokemon1", "prince", "princess", "princess1", "purple", "purple1", "q1w2e3", "q1w2e3r4", "q1w2e3r4t5", "q1w2e3r4t5y6", "qazwsx", "qazwsxedc", "qqqqqq", "qwaszx", "qwe123", "qweasd", "qweasdzxc", "qweqwe", "qwer1234", "qwert", "qwerty", "qwerty1", "qwerty12", "qwerty123", "qwerty12345", "qwertyu", "qwertyuiop", "rachel", "rainbow", "red123", "richard", "robert", "robert1", "salom", "samantha", "samarqand", "samsung", "samuel", "sandra", "school", "scooter", "secret", "shadow", "shadow1", "silver", "slipknot", "snoopy", "soccer", "soccer1", "sophie", "spiderman", "starwars", "status", "steven", "summer", "sunshine", "sunshine1", "superman", "superman1", "target123", "tashkent", "taylor", "thomas", "tigger", "tinkerbell", "tinkle", "toshkent", "trustno1", "tudelft", "u38fa39", "user", "uzbekistan", "vanessa", "victoria", "vqsablpzla", "wall.e", "welcome", "welcome1", "whatever", "william", "william1", "xbox360", "xxxxxx", "yellow", "zag12wsx", "zaq12wsx", "zxcvbn", "zxcvbnm", "йцукен", "йцукенгш", "пароль", "привет", "ташкент", "узбекистан"]);

const deleet = (value) => value.replace(/[@430$51!7]/g, (ch) => LEET[ch]);
// Strip non-letters at both ends. (`\W` would also strip Cyrillic in JS.)
const stripEdges = (value) => value.replace(/^[^\p{L}]+|[^\p{L}]+$/gu, "");

function isCommon(normalized) {
  const base = stripEdges(normalized);
  return [normalized, base, deleet(normalized), deleet(base)].some((item) => item.length >= 4 && COMMON.has(item));
}

function isSequence(normalized) {
  const compact = normalized.replace(/ /g, "");
  if (new Set(compact).size < 4) return true;
  const steps = new Set();
  for (let i = 1; i < compact.length; i += 1) steps.add(compact.codePointAt(i) - compact.codePointAt(i - 1));
  if (steps.size === 1 && (steps.has(1) || steps.has(-1))) return true;
  return KEYBOARD_ROWS.some((row) => row.includes(compact) || [...row].reverse().join("").includes(compact));
}

function personalFragments(email, fullName) {
  const local = String(email || "").split("@")[0];
  const words = `${local} ${fullName || ""}`.toLowerCase().split(/[^\p{L}]+/u);
  const fragments = new Set(words.filter((word) => word.length >= 4));
  const compactLocal = local.toLowerCase().replace(/[^\p{L}\p{N}_]/gu, "");
  if (compactLocal.length >= 4) fragments.add(compactLocal);
  return fragments;
}

function refusal(password, email, fullName) {
  if (password.length < MIN_LENGTH) return "too_short";
  if (password.length > MAX_LENGTH) return "too_long";
  const normalized = password.trim().toLowerCase();
  if (SITE_WORDS.some((word) => normalized.includes(word))) return "context";
  if (isCommon(normalized)) return "common";
  if (isSequence(normalized)) return "sequence";
  for (const fragment of personalFragments(email, fullName)) if (normalized.includes(fragment)) return "personal";
  return null;
}

export function passwordStrength(password, { email = "", fullName = "" } = {}) {
  const value = String(password || "");
  if (!value) return { level: "empty", score: 0, reason: null, acceptable: false };
  const reason = refusal(value, email, fullName);
  if (reason) return { level: "weak", score: 1, reason, acceptable: false };
  const classes = [/\p{Ll}/u, /\p{Lu}/u, /\d/, /[^\p{L}\d]/u].filter((re) => re.test(value)).length;
  let level = "fair";
  if (value.length >= 16 || (value.length >= 12 && classes >= 3)) level = "strong";
  else if (value.length >= 12 || (value.length >= 10 && classes >= 3)) level = "good";
  return { level, score: { fair: 2, good: 3, strong: 4 }[level], reason: null, acceptable: true };
}

const TEXT = {
  ru: {
    levels: { weak: "Слабый", fair: "Средний", good: "Хороший", strong: "Надёжный" },
    reasons: {
      too_short: "Минимум 8 символов.",
      too_long: "Не больше 128 символов.",
      common: "Пароль слишком распространён — такие подбирают первыми.",
      sequence: "Уберите последовательности и повторы (1234, qwerty, aaaa).",
      context: "Не используйте название сайта.",
      personal: "Не используйте своё имя или email.",
    },
    fair: "Можно надёжнее: длиннее лучше, например фраза из 3–4 слов.",
    good: "Хорошо. Чем длиннее, тем надёжнее.",
    strong: "Такой пароль сложно подобрать.",
  },
  uz: {
    levels: { weak: "Zaif", fair: "O‘rtacha", good: "Yaxshi", strong: "Kuchli" },
    reasons: {
      too_short: "Kamida 8 ta belgi.",
      too_long: "Ko‘pi bilan 128 ta belgi.",
      common: "Parol juda keng tarqalgan — bunday parollar birinchi bo‘lib topiladi.",
      sequence: "Ketma-ketlik va takrorlardan qoching (1234, qwerty, aaaa).",
      context: "Sayt nomidan foydalanmang.",
      personal: "Ismingiz yoki emailingizdan foydalanmang.",
    },
    fair: "Yanada kuchliroq bo‘lishi mumkin: uzunroq yaxshi, masalan 3–4 so‘zli ibora.",
    good: "Yaxshi. Qanchalik uzun bo‘lsa, shunchalik ishonchli.",
    strong: "Bunday parolni topish qiyin.",
  },
  en: {
    levels: { weak: "Weak", fair: "Fair", good: "Good", strong: "Strong" },
    reasons: {
      too_short: "At least 8 characters.",
      too_long: "At most 128 characters.",
      common: "This password is too common — it is among the first ones guessed.",
      sequence: "Avoid sequences and repeats (1234, qwerty, aaaa).",
      context: "Do not use the site name.",
      personal: "Do not use your name or email.",
    },
    fair: "Could be stronger: longer is better, e.g. a phrase of 3–4 words.",
    good: "Good. Longer is even safer.",
    strong: "A password like this is hard to guess.",
  },
};

const pick = (language) => TEXT[language] || TEXT.ru;

export function passwordLevelLabel(strength, language) {
  return pick(language).levels[strength.level] || "";
}

export function passwordHint(strength, language) {
  const text = pick(language);
  if (strength.reason) return text.reasons[strength.reason];
  return text[strength.level] || "";
}

// Server messages (password_policy.MESSAGES and the login lock) arrive in
// English; show them in the reader's language.
const SERVER_REASONS = {
  "Password must be at least 8 characters long": "too_short",
  "Password must be at most 128 characters long": "too_long",
  "The password must not contain the site name": "context",
  "This password is too common — choose a less predictable one": "common",
  "Avoid keyboard or number sequences and repeated characters": "sequence",
  "The password must not contain your name or email": "personal",
};

export function translateAuthError(message, language) {
  const text = String(message || "");
  const reason = SERVER_REASONS[text];
  if (reason) return pick(language).reasons[reason];
  const locked = text.match(/^Too many failed sign-in attempts\. Try again in (\d+) min/);
  if (locked) {
    const minutes = locked[1];
    return {
      ru: `Слишком много неудачных попыток входа. Попробуйте через ${minutes} мин или восстановите пароль.`,
      uz: `Kirishga juda ko‘p muvaffaqiyatsiz urinish. ${minutes} daqiqadan so‘ng urinib ko‘ring yoki parolni tiklang.`,
      en: `Too many failed sign-in attempts. Try again in ${minutes} min or reset your password.`,
    }[language] || text;
  }
  if (text === "Invalid email or password") {
    return { ru: "Неверный email или пароль.", uz: "Email yoki parol noto‘g‘ri.", en: "Invalid email or password." }[language] || text;
  }
  return text;
}
