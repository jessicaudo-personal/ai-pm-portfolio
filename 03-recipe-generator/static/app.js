const form = document.querySelector("#recipe-form");
const submitButton = document.querySelector("#submit-button");
const resultsRegion = document.querySelector(".results-column");
const resultsElement = document.querySelector("#results");
const emptyState = document.querySelector("#empty-state");
const statusMessage = document.querySelector("#status-message");
const downloadButton = document.querySelector("#download-button");

let latestMarkdown = "";
let currentResult = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function addSection(parent, title, className = "") {
  const section = element("section", `result-section ${className}`.trim());
  section.append(element("h3", "", title));
  parent.append(section);
  return section;
}

function showStatus(message, kind) {
  statusMessage.hidden = false;
  statusMessage.className = `status-message ${kind}`;
  statusMessage.textContent = message;
}

async function readApiResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    if (response.status === 404) {
      throw new Error(
        "The local app is out of date. Stop it with Ctrl+C, restart with python3 app-recipe.py, then refresh this page.",
      );
    }
    throw new Error("The local app returned an unexpected response. Restart it and try again.");
  }
  return response.json();
}

function clearResults() {
  resultsElement.replaceChildren();
  resultsElement.hidden = true;
  emptyState.hidden = false;
  downloadButton.hidden = true;
  latestMarkdown = "";
}

function renderRecipe(recipe, index, result) {
  const article = element("article", "recipe-card");
  const heading = element("div", "recipe-title-row");
  const title = element("div", "recipe-heading");
  title.append(
    element("span", "recipe-index", String(index + 1).padStart(2, "0")),
    element("h2", "", recipe.name || "Recipe idea"),
  );
  const regenerateButton = element("button", "recipe-regen", "Try another");
  regenerateButton.type = "button";
  regenerateButton.dataset.recipeIndex = String(index);
  regenerateButton.setAttribute("aria-label", `Try another recipe instead of ${recipe.name || "this idea"}`);
  regenerateButton.title = "Uses the OpenAI API to replace this recipe and update the shopping list and nutrition.";
  title.append(regenerateButton);
  heading.append(title);
  article.append(heading);

  const details = [];
  if (recipe.estimated_minutes) details.push(`${recipe.estimated_minutes} min`);
  if (recipe.servings) details.push(`${recipe.servings} servings`);
  if (details.length) article.append(element("p", "recipe-meta", details.join("  ·  ")));

  const ingredients = addSection(article, "Ingredients");
  const ingredientList = element("ul", "ingredient-list");
  for (const item of recipe.ingredients || []) {
    ingredientList.append(element(
      "li",
      "",
      [item.amount, item.name].filter(Boolean).join(" "),
    ));
  }
  ingredients.append(ingredientList);

  const steps = addSection(article, "How to make it");
  const stepList = element("ol", "step-list");
  for (const step of recipe.steps || []) stepList.append(element("li", "", step));
  steps.append(stepList);

  const verification = (result.verifications?.verifications || [])
    .find((item) => item.recipe_name === recipe.name);
  const constraint = recipe.constraint_check || {};
  const passes = verification ? verification.passes : constraint.met;
  const check = addSection(article, "AI constraint check (not allergy safety verification)", "check-section");
  check.append(element(
    "p",
    passes ? "check-status passed" : "check-status needs-attention",
    passes ? "No stated constraint mismatch flagged" : "Potential mismatch flagged",
  ));
  if (constraint.explanation) check.append(element("p", "detail-copy", constraint.explanation));
  check.append(element(
    "p",
    "detail-copy",
    "This AI check cannot confirm allergen safety, ingredient-label accuracy, or cross-contact risk.",
  ));
  for (const issue of verification?.issues || []) {
    check.append(element("p", "detail-copy", issue));
  }

  const nutrition = (result.nutrition?.nutrition || [])
    .find((item) => item.recipe_name === recipe.name);
  if (nutrition) {
    const nutritionSection = addSection(article, "Estimated nutrition per serving", "nutrition-section");
    const metrics = element("div", "nutrition-grid");
    for (const [label, value, unit] of [
      ["Calories", nutrition.calories, "kcal"],
      ["Protein", nutrition.protein_g, "g"],
      ["Carbs", nutrition.carbs_g, "g"],
      ["Fat", nutrition.fat_g, "g"],
    ]) {
      const metric = element("div", "nutrition-metric");
      metric.append(
        element("span", "metric-label", label),
        element("strong", "", value == null ? "—" : `${value} ${unit}`),
      );
      metrics.append(metric);
    }
    nutritionSection.append(metrics);
    if (nutrition.note) nutritionSection.append(element("p", "detail-copy", nutrition.note));
  }
  resultsElement.append(article);
}

function renderResults(result) {
  clearResults();
  currentResult = result;
  latestMarkdown = result.markdown || "";
  const allergyNotice = element(
    "aside",
    "allergy-warning",
    "Allergy safety reminder: AI-generated recipes are not guaranteed to be allergen-safe. Always verify ingredient labels (including packaged products) and check for cross-contact during preparation. Do not rely on this tool alone for allergy safety.",
  );
  allergyNotice.setAttribute("role", "note");
  resultsElement.append(allergyNotice);

  for (const [index, recipe] of (result.recipes?.recipes || []).entries()) {
    renderRecipe(recipe, index, result);
  }

  const shoppingSection = addSection(resultsElement, "Shopping list", "shopping-card");
  const shoppingItems = result.shopping?.shopping_list || [];
  if (shoppingItems.length) {
    const shoppingList = element("ul", "shopping-list");
    for (const item of shoppingItems) {
      shoppingList.append(element("li", "", [item.amount, item.name].filter(Boolean).join(" ")));
    }
    shoppingSection.append(shoppingList);
  } else {
    shoppingSection.append(element("p", "detail-copy", "Nothing extra to buy."));
  }

  const runDetails = element("p", "run-details", `Approx. ${result.total_tokens || 0} tokens used`);
  if (result.saved_file) {
    runDetails.append(document.createTextNode(` · Saved locally as ${result.saved_file}`));
  }
  resultsElement.append(runDetails);
  resultsElement.hidden = false;
  downloadButton.hidden = !latestMarkdown;
  emptyState.hidden = true;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearResults();
  currentResult = null;
  showStatus("Putting your recipe ideas together…", "success");
  resultsRegion.setAttribute("aria-busy", "true");
  submitButton.disabled = true;
  submitButton.querySelector(".button-label").textContent = "Making your recipes…";

  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  payload.recipe_count = Number(payload.recipe_count);

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await readApiResponse(response);
    if (!response.ok) throw new Error(body.error || "Recipe generation failed. Please try again.");
    renderResults(body.result);
    showStatus("Your recipe ideas are ready.", "success");
  } catch (error) {
    showStatus(error.message || "Could not reach the local app. Check that it is still running.", "error");
  } finally {
    resultsRegion.setAttribute("aria-busy", "false");
    submitButton.disabled = false;
    submitButton.querySelector(".button-label").textContent = "Find my recipes";
  }
});

resultsElement.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-recipe-index]");
  if (!button || !currentResult) return;

  const recipeIndex = Number(button.dataset.recipeIndex);
  const recipeName = currentResult.recipes.recipes[recipeIndex]?.name || "this recipe";
  resultsRegion.setAttribute("aria-busy", "true");
  submitButton.disabled = true;
  resultsElement.querySelectorAll(".recipe-regen").forEach((item) => {
    item.disabled = true;
  });
  showStatus(`Finding a different idea to replace ${recipeName}…`, "loading");

  try {
    const response = await fetch("/api/regenerate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_result: currentResult, recipe_index: recipeIndex }),
    });
    const body = await readApiResponse(response);
    if (!response.ok) throw new Error(body.error || "Could not find a replacement. Please try again.");
    renderResults(body.result);
    showStatus(`${recipeName} was replaced with a new idea.`, "success");
  } catch (error) {
    showStatus(error.message || "Could not reach the local app. Check that it is still running.", "error");
  } finally {
    resultsRegion.setAttribute("aria-busy", "false");
    submitButton.disabled = false;
    resultsElement.querySelectorAll(".recipe-regen").forEach((item) => {
      item.disabled = false;
    });
  }
});

downloadButton.addEventListener("click", () => {
  const blob = new Blob([latestMarkdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "my-recipes.md";
  link.click();
  URL.revokeObjectURL(url);
});
