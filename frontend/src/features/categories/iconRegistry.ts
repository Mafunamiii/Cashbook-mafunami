import type { LucideIcon } from "lucide-react";
import {
  Apple,
  Baby,
  Banknote,
  Bike,
  BookOpen,
  BriefcaseBusiness,
  Building2,
  Bus,
  CakeSlice,
  CalendarDays,
  Camera,
  Car,
  CircleDollarSign,
  CircleHelp,
  CircleCheck,
  ClipboardList,
  Coffee,
  Coins,
  Cloud,
  CookingPot,
  CupSoda,
  CreditCard,
  Dumbbell,
  FileText,
  Film,
  Footprints,
  Fuel,
  Gamepad2,
  Gift,
  GraduationCap,
  Hammer,
  HandCoins,
  Headphones,
  Heart,
  HeartPulse,
  Hospital,
  House,
  KeyRound,
  Lamp,
  Landmark,
  Laptop,
  Library,
  MapPin,
  MoreHorizontal,
  Music,
  NotebookPen,
  Package,
  Palette,
  PawPrint,
  PiggyBank,
  Pill,
  Plane,
  Receipt,
  Refrigerator,
  Salad,
  School,
  ShieldCheck,
  Shirt,
  ShoppingBag,
  ShoppingCart,
  Smartphone,
  Sofa,
  Stethoscope,
  Store,
  Tags,
  Ticket,
  TrainFront,
  Tv,
  Trophy,
  Utensils,
  UserRound,
  Users,
  WalletCards,
  Wifi,
  Wine,
  Wrench,
  Zap,
  Umbrella,
  TreePine,
  Trash2,
  Star,
} from "lucide-react";

export type IconGroup =
  | "Finance"
  | "Food & Dining"
  | "Shopping"
  | "Transport"
  | "Home & Utilities"
  | "Health"
  | "Entertainment"
  | "Education"
  | "Travel"
  | "Work"
  | "Family / Personal"
  | "Other";

export type CategoryIconDefinition = {
  key: string;
  label: string;
  keywords: string[];
  group: IconGroup;
  icon: LucideIcon;
};

const entry = (
  key: string,
  label: string,
  group: IconGroup,
  icon: LucideIcon,
  keywords: string[] = [],
): CategoryIconDefinition => ({ key, label, group, icon, keywords });

export const CATEGORY_ICON_REGISTRY: CategoryIconDefinition[] = [
  entry("wallet-cards", "Wallet", "Finance", WalletCards, ["money", "cash"]),
  entry("banknote", "Banknote", "Finance", Banknote, ["money", "cash", "salary"]),
  entry("coins", "Coins", "Finance", Coins, ["money", "cash", "change"]),
  entry("credit-card", "Credit card", "Finance", CreditCard, ["payment", "bank"]),
  entry("landmark", "Bank", "Finance", Landmark, ["finance", "banking"]),
  entry("circle-dollar-sign", "Dollar", "Finance", CircleDollarSign, ["money", "income"]),
  entry("piggy-bank", "Savings", "Finance", PiggyBank, ["money", "save"]),
  entry("receipt", "Receipt", "Finance", Receipt, ["bill", "expense"]),
  entry("hand-coins", "Allowance", "Finance", HandCoins, ["money", "income"]),
  entry("utensils", "Utensils", "Food & Dining", Utensils, ["food", "restaurant", "dining", "meal"]),
  entry("salad", "Salad", "Food & Dining", Salad, ["food", "healthy", "meal"]),
  entry("cup-soda", "Drinks", "Food & Dining", CupSoda, ["food", "drink", "beverage"]),
  entry("coffee", "Coffee", "Food & Dining", Coffee, ["food", "cafe", "drink"]),
  entry("cake-slice", "Cake", "Food & Dining", CakeSlice, ["food", "dessert", "birthday"]),
  entry("apple", "Groceries", "Food & Dining", Apple, ["food", "fruit", "market"]),
  entry("cooking-pot", "Cooking", "Food & Dining", CookingPot, ["food", "kitchen", "meal"]),
  entry("wine", "Wine", "Food & Dining", Wine, ["food", "drink", "bar"]),
  entry("shopping-cart", "Shopping cart", "Shopping", ShoppingCart, ["grocery", "store"]),
  entry("shopping-bag", "Shopping bag", "Shopping", ShoppingBag, ["store", "retail"]),
  entry("store", "Store", "Shopping", Store, ["shop", "retail"]),
  entry("tags", "Tags", "Shopping", Tags, ["sale", "discount"]),
  entry("gift", "Gift", "Shopping", Gift, ["present", "birthday"]),
  entry("shirt", "Clothing", "Shopping", Shirt, ["clothes", "fashion"]),
  entry("package", "Package", "Shopping", Package, ["delivery", "shipping"]),
  entry("smartphone", "Phone", "Shopping", Smartphone, ["mobile", "device", "electronics"]),
  entry("car", "Car", "Transport", Car, ["vehicle", "auto", "drive"]),
  entry("bus", "Bus", "Transport", Bus, ["public", "transit"]),
  entry("train-front", "Train", "Transport", TrainFront, ["public", "transit", "commute"]),
  entry("bike", "Bicycle", "Transport", Bike, ["cycle", "commute"]),
  entry("fuel", "Fuel", "Transport", Fuel, ["gas", "petrol"]),
  entry("footprints", "Walking", "Transport", Footprints, ["walk", "commute"]),
  entry("house", "Home", "Home & Utilities", House, ["rent", "housing"]),
  entry("sofa", "Furniture", "Home & Utilities", Sofa, ["home", "furniture"]),
  entry("lamp", "Home goods", "Home & Utilities", Lamp, ["home", "light"]),
  entry("refrigerator", "Appliances", "Home & Utilities", Refrigerator, ["home", "kitchen"]),
  entry("wrench", "Repairs", "Home & Utilities", Wrench, ["maintenance", "service"]),
  entry("zap", "Electricity", "Home & Utilities", Zap, ["utility", "power"]),
  entry("wifi", "Internet", "Home & Utilities", Wifi, ["utility", "connection"]),
  entry("heart-pulse", "Health", "Health", HeartPulse, ["medical", "wellness"]),
  entry("pill", "Medicine", "Health", Pill, ["medical", "pharmacy"]),
  entry("stethoscope", "Doctor", "Health", Stethoscope, ["medical", "clinic"]),
  entry("hospital", "Hospital", "Health", Hospital, ["medical", "clinic"]),
  entry("dumbbell", "Fitness", "Health", Dumbbell, ["gym", "exercise"]),
  entry("baby", "Baby care", "Health", Baby, ["health", "child"]),
  entry("film", "Movies", "Entertainment", Film, ["cinema", "watch"]),
  entry("music", "Music", "Entertainment", Music, ["concert", "audio"]),
  entry("gamepad-2", "Games", "Entertainment", Gamepad2, ["gaming", "hobby"]),
  entry("tv", "Television", "Entertainment", Tv, ["streaming", "show"]),
  entry("ticket", "Events", "Entertainment", Ticket, ["concert", "cinema"]),
  entry("camera", "Photography", "Entertainment", Camera, ["photo", "hobby"]),
  entry("headphones", "Audio", "Entertainment", Headphones, ["music", "podcast"]),
  entry("palette", "Art", "Entertainment", Palette, ["creative", "hobby"]),
  entry("graduation-cap", "Education", "Education", GraduationCap, ["school", "study"]),
  entry("school", "School", "Education", School, ["study", "class"]),
  entry("library", "Library", "Education", Library, ["books", "study"]),
  entry("book-open", "Books", "Education", BookOpen, ["reading", "study"]),
  entry("notebook-pen", "Supplies", "Education", NotebookPen, ["school", "stationery"]),
  entry("travel-map-pin", "Travel map", "Travel", MapPin, ["trip", "location"]),
  entry("plane", "Flight", "Travel", Plane, ["trip", "airport"]),
  entry("calendar-days", "Trips", "Travel", CalendarDays, ["holiday", "vacation"]),
  entry("umbrella", "Holiday", "Travel", Umbrella, ["trip", "vacation"]),
  entry("briefcase-business", "Work", "Work", BriefcaseBusiness, ["job", "business"]),
  entry("building-2", "Office", "Work", Building2, ["job", "business"]),
  entry("laptop", "Computer", "Work", Laptop, ["job", "office", "device"]),
  entry("clipboard-list", "Projects", "Work", ClipboardList, ["job", "tasks"]),
  entry("file-text", "Documents", "Work", FileText, ["job", "office"]),
  entry("hammer", "Tools", "Work", Hammer, ["work", "trade"]),
  entry("heart", "Personal", "Family / Personal", Heart, ["self", "care"]),
  entry("paw-print", "Pets", "Family / Personal", PawPrint, ["animal", "pet"]),
  entry("users", "Family", "Family / Personal", Users, ["people", "household"]),
  entry("user-round", "Personal", "Family / Personal", UserRound, ["person", "self"]),
  entry("shield-check", "Insurance", "Family / Personal", ShieldCheck, ["protection", "policy"]),
  entry("key-round", "Keys", "Family / Personal", KeyRound, ["home", "security"]),
  entry("star", "Special", "Family / Personal", Star, ["personal", "favorite"]),
  entry("tree-pine", "Outdoors", "Family / Personal", TreePine, ["nature", "hobby"]),
  entry("trophy", "Achievement", "Family / Personal", Trophy, ["award", "goal"]),
  entry("trash-2", "Waste", "Home & Utilities", Trash2, ["home", "service"]),
  entry("circle-check", "Completed", "Other", CircleCheck, ["done", "miscellaneous"]),
  entry("more-horizontal", "More", "Other", MoreHorizontal, ["miscellaneous", "general"]),
  entry("cloud", "Cloud services", "Other", Cloud, ["subscription", "online"]),
  entry("circle-help", "Other", "Other", CircleHelp, ["miscellaneous", "general"]),
];

const iconsByKey = new Map(CATEGORY_ICON_REGISTRY.map((definition) => [definition.key, definition]));

export function findCategoryIcon(value: string | null | undefined): CategoryIconDefinition | null {
  return value ? iconsByKey.get(value) ?? null : null;
}

export function searchCategoryIcons(query: string, group?: IconGroup): CategoryIconDefinition[] {
  const normalized = query.trim().toLocaleLowerCase();
  return CATEGORY_ICON_REGISTRY.filter((definition) => {
    if (group && definition.group !== group) return false;
    if (!normalized) return true;
    return [definition.key, definition.label, ...definition.keywords]
      .join(" ")
      .toLocaleLowerCase()
      .includes(normalized);
  });
}

export const CATEGORY_ICON_GROUPS: IconGroup[] = [
  "Finance", "Food & Dining", "Shopping", "Transport", "Home & Utilities", "Health",
  "Entertainment", "Education", "Travel", "Work", "Family / Personal", "Other",
];
