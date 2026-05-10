"""Pydantic models for meal JSON input."""

from typing import Optional

from pydantic import BaseModel, Field


class Macronutrients(BaseModel):
    protein_g: float = Field(ge=0)
    carbohydrates_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    fiber_g: float = Field(default=0, ge=0)
    sugar_g: float = Field(default=0, ge=0)


class Micronutrients(BaseModel):
    sodium_mg: float = Field(default=0, ge=0)
    potassium_mg: float = Field(default=0, ge=0)
    calcium_mg: float = Field(default=0, ge=0)
    iron_mg: float = Field(default=0, ge=0)
    vitamin_c_mg: float = Field(default=0, ge=0)


class MealInput(BaseModel):
    meal_name: str = Field(default="")
    serving_size: str = ""
    calories_kcal: float = Field(gt=0)
    macronutrients: Macronutrients
    micronutrients: Optional[Micronutrients] = None
    # Optional; otherwise filled from mapping sheet + UI (finance-style category / subcategory).
    category: Optional[str] = None
    subcategory: Optional[str] = None
