"""Paths and column names for fitness tracker."""

paths = {
    "maincss": "static/main.css",
    "meals_csv": "data/meals.csv",
    "targets_json": "data/daily_targets.json",
    "last_gsheets_sync": "data/last_gsheets_sync.txt",
    "food_categories_config": "data/food_categories.json",
    "food_mappings_local": "data/food_mappings.json",
    "inference_learned": "data/meal_inference_learned.json",
    "inference_word_scores": "data/meal_inference_word_scores.json",
}

# Spreadsheet ID is overridden by st.secrets["FITNESS_SPREADSHEET_ID"] when set.
DEFAULT_SPREADSHEET_ID = "your-spreadsheet-id-here"
MEALS_WORKSHEET_NAME = "Meals"
MISC_WORKSHEET_NAME = "Misc"
# Tab with meal-key → category / subcategory (same idea as finance-dashboard "Mappings").
# Set FITNESS_FOOD_MAPPINGS_WORKSHEET in secrets to your tab name (gid in URL ≠ tab name).
DEFAULT_FOOD_MAPPINGS_WORKSHEET = "FoodMappings"

# Default food taxonomy (category → subcategories). User additions merge in, like finance categories.
DEFAULT_FOOD_SUBCATEGORIES: dict[str, list[str]] = {
    "Meal": ["Rice / noodles", "Salad", "Sandwich / wrap", "Mixed plate", "Other"],
    "Snack": ["Sweet", "Savory", "Protein snack", "Other"],
    "Beverage": ["Coffee / tea", "Juice / smoothie", "Soft drink", "Other"],
    "Uncategorized": ["Other"],
}

MEAL_COLUMNS = [
    "MEAL_DATE",
    "LOGGED_AT",
    "MEAL_NAME",
    "CATEGORY",
    "SUBCATEGORY",
    "SERVING_SIZE",
    "CALORIES_KCAL",
    "PROTEIN_G",
    "CARBOHYDRATES_G",
    "FAT_G",
    "FIBER_G",
    "SUGAR_G",
    "SODIUM_MG",
    "POTASSIUM_MG",
    "CALCIUM_MG",
    "IRON_MG",
    "VITAMIN_C_MG",
    "SOURCE",
]
