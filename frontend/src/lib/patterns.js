// Chart-pattern vocabulary shared by the charts, the bell and the settings.
// Keys are pattern_engine.py's types; the order of the two lists is the order
// the settings page offers them in.

export const PATTERN_NAMES = {
  double_top: ["Двойная вершина", "Qo'sh cho'qqi", "Double top"],
  double_bottom: ["Двойное дно", "Qo'sh tub", "Double bottom"],
  triple_top: ["Тройная вершина", "Uch karra cho'qqi", "Triple top"],
  triple_bottom: ["Тройное дно", "Uch karra tub", "Triple bottom"],
  head_shoulders: ["Голова и плечи", "Bosh va yelkalar", "Head and shoulders"],
  inverse_head_shoulders: ["Перевёрнутые голова и плечи", "Teskari bosh va yelkalar", "Inverse head and shoulders"],
  ascending_triangle: ["Восходящий треугольник", "O'suvchi uchburchak", "Ascending triangle"],
  descending_triangle: ["Нисходящий треугольник", "Pasayuvchi uchburchak", "Descending triangle"],
  symmetrical_triangle: ["Симметричный треугольник", "Simmetrik uchburchak", "Symmetrical triangle"],
  rising_wedge: ["Восходящий клин", "O'suvchi pona", "Rising wedge"],
  falling_wedge: ["Нисходящий клин", "Pasayuvchi pona", "Falling wedge"],
  ascending_channel: ["Восходящий канал", "O'suvchi kanal", "Ascending channel"],
  descending_channel: ["Нисходящий канал", "Pasayuvchi kanal", "Descending channel"],
  horizontal_channel: ["Боковой канал", "Gorizontal kanal", "Horizontal channel"],
  bull_flag: ["Бычий флаг", "Buqa bayrog'i", "Bull flag"],
  bear_flag: ["Медвежий флаг", "Ayiq bayrog'i", "Bear flag"],
  bull_pennant: ["Бычий вымпел", "Buqa vimpeli", "Bull pennant"],
  bear_pennant: ["Медвежий вымпел", "Ayiq vimpeli", "Bear pennant"],
  bullish_engulfing: ["Бычье поглощение", "Buqa yutilishi", "Bullish engulfing"],
  bearish_engulfing: ["Медвежье поглощение", "Ayiq yutilishi", "Bearish engulfing"],
  hammer: ["Молот", "Bolg'a", "Hammer"],
  shooting_star: ["Падающая звезда", "Tushayotgan yulduz", "Shooting star"],
  morning_star: ["Утренняя звезда", "Tong yulduzi", "Morning star"],
  evening_star: ["Вечерняя звезда", "Oqshom yulduzi", "Evening star"],
};

export const patternName = (type, lang) => (PATTERN_NAMES[type] || [type, type, type])[lang === "uz" ? 1 : lang === "en" ? 2 : 0];

export const CHART_PATTERN_TYPES = [
  "double_top", "double_bottom", "triple_top", "triple_bottom", "head_shoulders", "inverse_head_shoulders",
  "ascending_triangle", "descending_triangle", "symmetrical_triangle", "rising_wedge", "falling_wedge",
  "ascending_channel", "descending_channel", "horizontal_channel", "bull_flag", "bear_flag",
  "bull_pennant", "bear_pennant",
];
export const CANDLE_PATTERN_TYPES = [
  "bullish_engulfing", "bearish_engulfing", "hammer", "shooting_star", "morning_star", "evening_star",
];
