document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("dynamic-event-form");

    if (!form) {
        return;
    }

    const submitButton = form.querySelector(".submit-button");
    let allSteps = Array.from(form.querySelectorAll(".wizard-step"));
    const previousButton = form.querySelector(".wizard-previous");
    const nextButton = form.querySelector(".wizard-next");
    const progressTrack = form.querySelector(".wizard-progress-track");
    const progressFill = form.querySelector(".wizard-progress-fill");
    const progressPercent = form.querySelector(".wizard-progress-percent");
    const stepCount = form.querySelector(".wizard-step-count");
    const stepDots = form.querySelector(".wizard-step-dots");
    const reviewContainer = form.querySelector(".review-sections");
    const language =
        document.documentElement.lang === "en" ? "en" : "sw";
    const draftAutosaveEnabled = form.dataset.draftAutosave === "true";
    const draftDataElement = document.getElementById("draft-answer-values");
    const pageUrl = new URL(window.location.href);
    const registrationDraft =
        draftAutosaveEnabled && !pageUrl.searchParams.has("participant");
    const draftStorageKey = `event-form-draft:${pageUrl.pathname}`;
    let draftToken = form.dataset.draftToken || "";
    let currentStep = 0;
    let draftSaveTimer = null;
    let draftSavePromise = null;
    let submissionInProgress = false;

    if (registrationDraft && !draftToken) {
        const savedDraftToken = window.localStorage.getItem(draftStorageKey);
        if (savedDraftToken) {
            pageUrl.searchParams.set("draft", savedDraftToken);
            window.location.replace(pageUrl.toString());
            return;
        }
    }

    const restoreDraftAnswers = () => {
        if (!draftDataElement) {
            return;
        }
        let draftAnswers = {};
        try {
            draftAnswers = JSON.parse(draftDataElement.textContent);
        } catch (error) {
            console.error("Could not restore the saved evaluation draft.", error);
            return;
        }
        Object.entries(draftAnswers).forEach(([questionKey, storedValue]) => {
            const values = Array.isArray(storedValue)
                ? storedValue.map(String)
                : [String(storedValue)];
            form.querySelectorAll(`[name="question_${questionKey}"]`)
                .forEach((control) => {
                    if (control.type === "checkbox" || control.type === "radio") {
                        control.checked = values.includes(control.value);
                    } else if (control.type !== "file") {
                        control.value = values[0] || "";
                    }
                });
        });
    };

    allSteps.forEach((step) => {
        step.querySelectorAll("input, select, textarea").forEach((control) => {
            control.dataset.originalRequired = control.required ? "true" : "false";
        });
    });

    const answerValues = (questionId, context = null) => {
        const step = context?.closest?.(".wizard-step");
        const repeatIndex = Number(step?.dataset.repeatIndex || 0);
        const name = repeatIndex
            ? `question_${questionId}__repeat_${repeatIndex}`
            : `question_${questionId}`;
        return Array.from(
        form.querySelectorAll(`[name="${name}"]`)
    ).filter((control) => !control.disabled).flatMap((control) => {
        if (control.type === "checkbox" || control.type === "radio") {
            return control.checked ? [control.value.trim()] : [];
        }
        return control.value.trim() ? [control.value.trim()] : [];
    });
    };

    const updateDynamicLabels = () => {
        form.querySelectorAll(".dynamic-label[data-label-template]").forEach((element) => {
            element.textContent = element.dataset.labelTemplate.replace(
                /\{\{\s*q(\d+)\s*\}\}/gi,
                (_match, questionId) => answerValues(questionId, element).join(", ") || "…"
            );
        });
        form.querySelectorAll(".form-field[data-question-id]").forEach((field) => {
            const label = field.querySelector(".dynamic-label")?.textContent.trim();
            if (label) field.dataset.questionLabel = label;
            const placeholder = (field.dataset.placeholderTemplate || "").replace(
                /\{\{\s*q(\d+)\s*\}\}/gi,
                (_match, questionId) => answerValues(questionId, field).join(", ") || "…"
            );
            field.querySelectorAll("input[placeholder], textarea[placeholder]")
                .forEach((control) => { control.placeholder = placeholder; });
        });
        allSteps.forEach((step) => {
            const title = step.querySelector(".section-header h3 .dynamic-label")?.textContent.trim();
            if (title) step.dataset.stepTitle = title;
        });
    };

    const calculateExpression = (expression, context = null) => {
        const source = expression.trim();
        const tokens = source.match(/q\d+|COUNT|SUM|IF|>=|<=|==|!=|>|<|\d+(?:\.\d+)?|[(),+\-*/%]/gi) || [];
        if (tokens.join("").toUpperCase() !== source.replace(/\s+/g, "").toUpperCase()) throw new Error("Invalid expression");
        let position = 0;
        const primary = (evaluate = true) => {
            const token = tokens[position++];
            if (/^q\d+$/i.test(token || "")) {
                if (!evaluate) return 0;
                const values = answerValues(token.slice(1), context);
                if (!values.length) throw new Error(`${token} is empty`);
                return values.length > 1 ? values : values[0];
            }
            if (/^(COUNT|SUM|IF)$/i.test(token || "")) {
                const functionName = token.toUpperCase();
                if (tokens[position++] !== "(") throw new Error("Missing parenthesis");
                if (functionName === "IF") {
                    const condition = comparison(evaluate);
                    if (tokens[position++] !== ",") throw new Error("IF needs three arguments");
                    const trueValue = comparison(evaluate && Boolean(condition));
                    if (tokens[position++] !== ",") throw new Error("IF needs three arguments");
                    const falseValue = comparison(evaluate && !Boolean(condition));
                    if (tokens[position++] !== ")") throw new Error("Missing parenthesis");
                    return evaluate ? (condition ? trueValue : falseValue) : 0;
                }
                const args = [];
                if (tokens[position] !== ")") {
                    do {
                        args.push(comparison(evaluate));
                    } while (tokens[position] === "," && ++position);
                }
                if (tokens[position++] !== ")") throw new Error("Missing parenthesis");
                if (!evaluate) return 0;
                if (functionName === "SUM") {
                    return args.flatMap((value) => Array.isArray(value) ? value : [value])
                        .reduce((total, value) => total + Number(value || 0), 0);
                }
                return args.reduce((count, value) => count + (Array.isArray(value) ? value.length : (value === "" ? 0 : 1)), 0);
            }
            if (token === "(") {
                const value = comparison(evaluate);
                if (tokens[position++] !== ")") throw new Error("Missing parenthesis");
                return value;
            }
            if (token === "+") return primary(evaluate);
            if (token === "-") return -primary(evaluate);
            const value = Number(token);
            if (!Number.isFinite(value)) throw new Error("Invalid number");
            return value;
        };
        const multiplication = (evaluate = true) => {
            let value = primary(evaluate);
            while (["*", "/", "%"].includes(tokens[position])) {
                const operator = tokens[position++];
                const right = Number(primary(evaluate));
                value = Number(value);
                value = operator === "*" ? value * right : operator === "/" ? value / right : value % right;
            }
            return value;
        };
        const addition = (evaluate = true) => {
            let value = Number(multiplication(evaluate));
            while (["+", "-"].includes(tokens[position])) {
                const operator = tokens[position++];
                const right = Number(multiplication(evaluate));
                value = operator === "+" ? value + right : value - right;
            }
            return value;
        };
        const comparison = (evaluate = true) => {
            let value = addition(evaluate);
            const operator = tokens[position];
            if (![">", ">=", "<", "<=", "==", "!="].includes(operator)) return value;
            position += 1;
            const right = addition(evaluate);
            if (operator === ">") return value > right;
            if (operator === ">=") return value >= right;
            if (operator === "<") return value < right;
            if (operator === "<=") return value <= right;
            if (operator === "==") return value === right;
            return value !== right;
        };
        const result = comparison();
        if (position !== tokens.length || !Number.isFinite(result)) throw new Error("Invalid result");
        return result;
    };

    const updateCalculatedFields = () => {
        form.querySelectorAll(".form-field[data-calculation-expression]").forEach((field) => {
            const control = field.querySelector("input");
            try {
                const result = calculateExpression(field.dataset.calculationExpression, field);
                control.value = result.toFixed(Number(field.dataset.decimalPlaces || 2));
            } catch (_error) {
                control.value = "";
            }
        });
    };

    const updateChoiceFilters = () => {
        form.querySelectorAll(".form-field[data-choice-filter-question]").forEach((field) => {
            const controllingValues = answerValues(field.dataset.choiceFilterQuestion, field);
            const controls = Array.from(field.querySelectorAll("option[data-filter-values], .choice-item[data-filter-values]"));
            controls.forEach((item) => {
                const allowedValues = (item.dataset.filterValues || "")
                    .split(",").map((value) => value.trim()).filter(Boolean);
                const show = !allowedValues.length || controllingValues.some(
                    (value) => allowedValues.includes(value)
                );
                const input = item.matches("option") ? item : item.querySelector("input");
                item.hidden = !show;
                if (input) {
                    input.disabled = !show;
                    if (!show) {
                        if (input.matches("option")) {
                            const select = input.closest("select");
                            if (select && select.value === input.value) select.value = "";
                        } else {
                            input.checked = false;
                        }
                    }
                }
            });
        });
    };

    const ruleMatches = (rule, context = null) => {
        const values = answerValues(rule.question, context);
        const comparedValues = rule.comparison_question
            ? answerValues(rule.comparison_question, context)
            : [];
        const expected = rule.comparison_question
            ? String(comparedValues[0] || "")
            : String(rule.value || "");
        const foldedExpected = expected.toLocaleLowerCase();
        switch (rule.operator) {
        case "ANSWERED": return values.length > 0;
        case "NOT_ANSWERED": return values.length === 0;
        case "EQUALS": return values.includes(expected);
        case "NOT_EQUALS": return !values.includes(expected);
        case "CONTAINS":
            return values.some((value) => value.toLocaleLowerCase().includes(foldedExpected));
        case "NOT_CONTAINS":
            return !values.some((value) => value.toLocaleLowerCase().includes(foldedExpected));
        case "STARTS_WITH":
            return values.some((value) => value.toLocaleLowerCase().startsWith(foldedExpected));
        case "ENDS_WITH":
            return values.some((value) => value.toLocaleLowerCase().endsWith(foldedExpected));
        case "ANY_OF": return values.some((value) => (rule.values || []).map(String).includes(value));
        case "NONE_OF": return !values.some((value) => (rule.values || []).map(String).includes(value));
        case "SELECTION_COUNT_EQUALS": return values.length === Number(expected);
        case "SELECTION_COUNT_AT_LEAST": return values.length >= Number(expected);
        case "SELECTION_COUNT_AT_MOST": return values.length <= Number(expected);
        case "GREATER_THAN": {
            const actualNumber = Number(values[0]);
            const expectedNumber = Number(expected);
            return values.length > 0 && Number.isFinite(actualNumber) &&
                Number.isFinite(expectedNumber) && actualNumber > expectedNumber;
        }
        case "GREATER_THAN_OR_EQUAL": {
            const actualNumber = Number(values[0]);
            const expectedNumber = Number(expected);
            return values.length > 0 && Number.isFinite(actualNumber) &&
                Number.isFinite(expectedNumber) && actualNumber >= expectedNumber;
        }
        case "LESS_THAN": {
            const actualNumber = Number(values[0]);
            const expectedNumber = Number(expected);
            return values.length > 0 && Number.isFinite(actualNumber) &&
                Number.isFinite(expectedNumber) && actualNumber < expectedNumber;
        }
        case "LESS_THAN_OR_EQUAL": {
            const actualNumber = Number(values[0]);
            const expectedNumber = Number(expected);
            return values.length > 0 && Number.isFinite(actualNumber) &&
                Number.isFinite(expectedNumber) && actualNumber <= expectedNumber;
        }
        case "BETWEEN": {
            const actualNumber = Number(values[0]);
            const lowerNumber = Number(expected);
            const upperNumber = Number(rule.value_end);
            return values.length > 0 && Number.isFinite(actualNumber) &&
                Number.isFinite(lowerNumber) && Number.isFinite(upperNumber) &&
                actualNumber >= lowerNumber && actualNumber <= upperNumber;
        }
        case "DATE_BEFORE": {
            const actualDate = Date.parse(values[0]);
            const expectedDate = Date.parse(expected);
            return Number.isFinite(actualDate) && Number.isFinite(expectedDate) &&
                actualDate < expectedDate;
        }
        case "DATE_AFTER": {
            const actualDate = Date.parse(values[0]);
            const expectedDate = Date.parse(expected);
            return Number.isFinite(actualDate) && Number.isFinite(expectedDate) &&
                actualDate > expectedDate;
        }
        default: return true;
        }
    };

    const logicMatches = (logic, context = null) => {
        const results = (logic.rules || []).map((rule) => ruleMatches(rule, context));
        (logic.groups || []).forEach((group) => results.push(logicMatches(group, context)));
        if (!results.length) {
            return true;
        }
        return logic.match === "ANY" ? results.some(Boolean) : results.every(Boolean);
    };

    const conditionMatches = (element) => {
        if (!element.dataset.displayLogic) {
            return true;
        }
        let logic;
        try {
            logic = JSON.parse(element.dataset.displayLogic);
        } catch (error) {
            console.error("Invalid questionnaire display logic.", error);
            return true;
        }
        return logicMatches(logic, element);
    };

    const getVisibleSteps = () => allSteps.filter(conditionMatches);

    const applyConditionalState = () => {
        const requiredMatches = (field) => {
            if (!field.dataset.requiredLogic) {
                return false;
            }
            try {
                return logicMatches(JSON.parse(field.dataset.requiredLogic), field);
            } catch (error) {
                console.error("Invalid questionnaire required logic.", error);
                return false;
            }
        };
        allSteps.forEach((step) => {
            const visible = conditionMatches(step);
            step.dataset.conditionVisible = visible ? "true" : "false";

            step.querySelectorAll("input, select, textarea").forEach((control) => {
                control.disabled = !visible;
                control.required = visible &&
                    control.dataset.originalRequired === "true";
                if (!visible) {
                    control.setCustomValidity("");
                }
            });
        });

        form.querySelectorAll(".form-field[data-display-logic]").forEach((field) => {
            const visible = conditionMatches(field);
            field.hidden = !visible;
            field.querySelectorAll("input, select, textarea").forEach((control) => {
                control.disabled = !visible;
                control.required = visible &&
                    control.dataset.originalRequired === "true";
                if (!visible) {
                    control.setCustomValidity("");
                }
            });
        });

        form.querySelectorAll(".form-field").forEach((field) => {
            const required = field.dataset.required === "true" || requiredMatches(field);
            const visible = !field.hidden && field.closest(".form-step")?.dataset.conditionVisible !== "false";
            field.querySelectorAll("input, select, textarea").forEach((control) => {
                control.required = visible && required && control.type !== "checkbox";
            });
            field.dataset.effectiveRequired = required ? "true" : "false";
        });
    };

    const originalButtonText = submitButton
        ? submitButton.textContent.trim()
        : "";

    const clearErrors = () => {
        form.querySelectorAll(".field-error").forEach((element) => {
            element.textContent = "";
            element.classList.remove("is-visible");
        });

        form.querySelectorAll(".form-field").forEach((element) => {
            element.classList.remove("has-error");
        });

        const oldMessage = form.querySelector(
            ".submission-message"
        );

        if (oldMessage) {
            oldMessage.remove();
        }
    };

    const text = {
        step: language === "en" ? "Step" : "Hatua",
        of: language === "en" ? "of" : "kati ya",
        complete: language === "en" ? "complete" : "imekamilika",
        notAnswered:
            language === "en" ? "Not answered" : "Haijajibiwa",
        noFile:
            language === "en" ? "No file selected" : "Hakuna faili",
        edit: language === "en" ? "Edit" : "Hariri",
    };

    const getFieldValue = (field) => {
        const controls = Array.from(
            field.querySelectorAll("input, select, textarea")
        );
        const checked = controls.filter(
            (control) =>
                (control.type === "checkbox" ||
                    control.type === "radio") &&
                control.checked
        );

        if (checked.length) {
            return checked.map((control) => {
                const choice = control.closest(".choice-item");
                return choice
                    ? choice.textContent.trim()
                    : control.dataset.optionLabel || control.value;
            }).join(", ");
        }

        const control = controls.find(
            (item) =>
                item.type !== "checkbox" &&
                item.type !== "radio" &&
                item.type !== "hidden"
        );

        if (!control) {
            return text.notAnswered;
        }

        if (control.type === "file") {
            return control.files && control.files.length
                ? Array.from(control.files)
                    .map((file) => file.name)
                    .join(", ")
                : text.noFile;
        }

        if (control.tagName === "SELECT" && control.selectedIndex >= 0) {
            return control.value
                ? control.options[control.selectedIndex].text.trim()
                : text.notAnswered;
        }

        return control.value.trim() || text.notAnswered;
    };

    const buildReview = () => {
        if (!reviewContainer) {
            return;
        }

        reviewContainer.replaceChildren();

        getVisibleSteps()
            .filter((step) => !step.classList.contains("wizard-review-step"))
            .forEach((step, index) => {
            const section = document.createElement("section");
            section.className = "review-section";

            const heading = document.createElement("div");
            heading.className = "review-section-heading";

            const title = document.createElement("h4");
            title.textContent = step.dataset.stepTitle;

            const editButton = document.createElement("button");
            editButton.type = "button";
            editButton.className = "review-edit-button";
            editButton.textContent = text.edit;
            editButton.addEventListener("click", () => showStep(index));

            heading.append(title, editButton);
            section.append(heading);

            step.querySelectorAll(".form-field").forEach((field) => {
                const item = document.createElement("div");
                item.className = "review-item";

                const label = document.createElement("dt");
                label.textContent = field.dataset.questionLabel;

                const value = document.createElement("dd");
                value.textContent = getFieldValue(field);

                item.append(label, value);
                section.append(item);
            });

            reviewContainer.append(section);
        });
    };

    const updateProgress = () => {
        const steps = getVisibleSteps();
        const total = steps.length;
        const percent = total
            ? Math.round(((currentStep + 1) / total) * 100)
            : 0;

        if (stepCount) {
            stepCount.textContent =
                `${text.step} ${currentStep + 1} ${text.of} ${total}`;
        }

        if (progressPercent) {
            progressPercent.textContent = `${percent}% ${text.complete}`;
        }

        if (progressFill) {
            progressFill.style.width = `${percent}%`;
        }

        if (progressTrack) {
            progressTrack.setAttribute("aria-valuenow", String(percent));
        }

        form.querySelectorAll(".wizard-step-dot").forEach((dot, index) => {
            dot.classList.toggle("is-active", index === currentStep);
            dot.classList.toggle("is-complete", index < currentStep);
            dot.setAttribute(
                "aria-current",
                index === currentStep ? "step" : "false"
            );
        });
    };

    const showStep = (index, focusHeading = true) => {
        const steps = getVisibleSteps();
        currentStep = Math.max(0, Math.min(index, steps.length - 1));

        allSteps.forEach((step) => {
            const stepIndex = steps.indexOf(step);
            const active = stepIndex === currentStep;
            step.hidden = !active;
            step.classList.toggle("is-active", active);

            const eyebrow = step.querySelector(".section-eyebrow");
            if (eyebrow) {
                eyebrow.textContent =
                    `${text.step} ${stepIndex + 1} ${text.of} ${steps.length}`;
            }
        });

        if (currentStep === steps.length - 1) {
            buildReview();
        }

        if (previousButton) {
            previousButton.hidden = currentStep === 0;
        }

        if (nextButton) {
            nextButton.hidden = currentStep === steps.length - 1;
        }

        if (submitButton) {
            submitButton.hidden = currentStep !== steps.length - 1;
        }

        updateProgress();

        if (focusHeading) {
            const heading = steps[currentStep].querySelector("h3");
            heading?.setAttribute("tabindex", "-1");
            heading?.focus({preventScroll: true});
            form.querySelector(".wizard-progress")?.scrollIntoView({
                behavior: "smooth",
                block: "start",
            });
        }
    };

    const validateCurrentStep = () => {
        const steps = getVisibleSteps();
        const step = steps[currentStep];
        const invalidVisualRule = Array.from(
            step.querySelectorAll(".form-field[data-validation-logic]")
        ).find((field) => {
            const hasAnswer = field.querySelectorAll("input:checked").length
                || Array.from(field.querySelectorAll("input, select, textarea"))
                    .some((control) => control.type !== "checkbox" && control.type !== "radio" && control.value);
            if (!hasAnswer) return false;
            try {
                return !logicMatches(JSON.parse(field.dataset.validationLogic), field);
            } catch (_error) {
                return true;
            }
        });
        if (invalidVisualRule) {
            const control = invalidVisualRule.querySelector("input, select, textarea");
            control?.setCustomValidity(
                invalidVisualRule.dataset.validationMessage
                || (language === "en" ? "This answer does not meet the validation rules." : "Jibu hili halikidhi masharti ya uthibitishaji.")
            );
            control?.reportValidity();
            control?.focus({preventScroll: true});
            return false;
        }
        const unansweredRequiredGroup = Array.from(
            step.querySelectorAll(
                '.form-field[data-effective-required="true"][data-question-type="MULTIPLE_CHOICE"]'
            )
        ).find((field) => !field.querySelector("input:checked"));

        if (unansweredRequiredGroup) {
            const firstChoice = unansweredRequiredGroup.querySelector("input");
            firstChoice?.setCustomValidity(
                language === "en"
                    ? "Select at least one option."
                    : "Chagua angalau chaguo moja."
            );
            firstChoice?.reportValidity();
            firstChoice?.focus({preventScroll: true});
            unansweredRequiredGroup.scrollIntoView({
                behavior: "smooth",
                block: "center",
            });
            return false;
        }

        const controls = Array.from(
            step.querySelectorAll("input, select, textarea")
        );
        const invalid = controls.find((control) => !control.checkValidity());

        if (!invalid) {
            return true;
        }

        invalid.reportValidity();
        invalid.focus({preventScroll: true});
        invalid.closest(".form-field")?.scrollIntoView({
            behavior: "smooth",
            block: "center",
        });
        return false;
    };

    if (allSteps.length) {
        form.classList.add("wizard-ready");

        const rebuildStepDots = () => {
            if (!stepDots) {
                return;
            }

            stepDots.replaceChildren();

            getVisibleSteps().forEach((step, index) => {
            const item = document.createElement("li");
            const button = document.createElement("button");
            button.type = "button";
            button.className = "wizard-step-dot";
            button.setAttribute(
                "aria-label",
                `${text.step} ${index + 1}: ${step.dataset.stepTitle}`
            );
            button.addEventListener("click", () => {
                if (index < currentStep) {
                    showStep(index);
                }
            });
            item.append(button);
            stepDots.append(item);
            });
        };

        const renumberRepeatSteps = (sectionId) => {
            const instances = allSteps.filter(
                (step) => step.dataset.sectionId === sectionId
            );
            instances.forEach((step, repeatIndex) => {
                step.dataset.repeatIndex = String(repeatIndex);
                step.querySelectorAll("input, select, textarea").forEach((control) => {
                    const baseName = control.name.replace(/__repeat_\d+$/, "");
                    if (baseName.startsWith("question_")) {
                        control.name = repeatIndex ? `${baseName}__repeat_${repeatIndex}` : baseName;
                    }
                });
                const remove = step.querySelector(".repeat-remove");
                if (remove) remove.hidden = repeatIndex === 0;
                if (repeatIndex) step.querySelector(".repeat-add")?.setAttribute("hidden", "hidden");
            });
            const original = instances[0];
            if (original) {
                original.querySelector(".repeat-count").value = String(instances.length);
                const add = original.querySelector(".repeat-add");
                if (add) add.hidden = instances.length >= Number(original.dataset.maxRepeats || 10);
            }
        };

        const addRepeatStep = (original) => {
            const sectionId = original.dataset.sectionId;
            const instances = allSteps.filter((step) => step.dataset.sectionId === sectionId);
            if (instances.length >= Number(original.dataset.maxRepeats || 10)) return;
            const clone = original.cloneNode(true);
            clone.querySelector(".repeat-count")?.remove();
            clone.querySelectorAll("input, select, textarea").forEach((control) => {
                if (control.type === "checkbox" || control.type === "radio") control.checked = false;
                else if (control.type !== "hidden") control.value = "";
                control.setCustomValidity("");
            });
            const reviewStep = allSteps.find((step) => step.classList.contains("wizard-review-step"));
            reviewStep.before(clone);
            allSteps = Array.from(form.querySelectorAll(".wizard-step"));
            renumberRepeatSteps(sectionId);
            updateChoiceFilters();
            updateCalculatedFields();
            updateDynamicLabels();
            applyConditionalState();
            rebuildStepDots();
        };

        form.addEventListener("click", (event) => {
            const add = event.target.closest(".repeat-add");
            if (add) {
                const current = add.closest(".wizard-step");
                const original = allSteps.find(
                    (step) => step.dataset.sectionId === current.dataset.sectionId
                        && step.dataset.repeatIndex === "0"
                );
                if (original) addRepeatStep(original);
                return;
            }
            const remove = event.target.closest(".repeat-remove");
            if (remove) {
                const step = remove.closest(".wizard-step");
                const sectionId = step.dataset.sectionId;
                const minimum = Number(step.dataset.minRepeats || 1);
                const instances = allSteps.filter((item) => item.dataset.sectionId === sectionId);
                if (instances.length <= minimum) return;
                step.remove();
                allSteps = Array.from(form.querySelectorAll(".wizard-step"));
                renumberRepeatSteps(sectionId);
                rebuildStepDots();
                showStep(Math.min(currentStep, getVisibleSteps().length - 1), false);
            }
        });

        allSteps.filter((step) => step.dataset.repeatable === "true").forEach((step) => {
            const draftIndexes = Object.keys(
                (() => {
                    try { return JSON.parse(draftDataElement?.textContent || "{}"); }
                    catch (_error) { return {}; }
                })()
            ).flatMap((key) => {
                const match = key.match(/__repeat_(\d+)$/);
                return match ? [Number(match[1])] : [];
            });
            const requiredCount = Math.max(
                Number(step.dataset.minRepeats || 1),
                draftIndexes.length ? Math.max(...draftIndexes) + 1 : 1,
            );
            for (let index = 1; index < requiredCount; index += 1) addRepeatStep(step);
        });

        restoreDraftAnswers();

        updateChoiceFilters();
        updateCalculatedFields();
        updateDynamicLabels();
        applyConditionalState();
        rebuildStepDots();

        form.addEventListener("change", (event) => {
            if (!event.target.matches("input, select, textarea")) {
                return;
            }

            event.target.closest(".form-field")
                ?.querySelectorAll("input, select, textarea")
                .forEach((control) => control.setCustomValidity(""));
            updateChoiceFilters();
            updateCalculatedFields();
            updateDynamicLabels();
            const activeStep = getVisibleSteps()[currentStep];
            applyConditionalState();
            const updatedSteps = getVisibleSteps();
            const updatedIndex = updatedSteps.indexOf(activeStep);
            currentStep = updatedIndex >= 0
                ? updatedIndex
                : Math.min(currentStep, updatedSteps.length - 1);
            rebuildStepDots();
            showStep(currentStep, false);
        });

        previousButton?.addEventListener(
            "click",
            () => showStep(currentStep - 1)
        );

        nextButton?.addEventListener("click", () => {
            if (validateCurrentStep()) {
                showStep(currentStep + 1);
            }
        });

        showStep(0, false);
    }

    const performDraftSave = async () => {
        if (!draftAutosaveEnabled || submissionInProgress) {
            return;
        }
        const formData = new FormData(form);
        formData.append("_save_draft", "1");
        if (draftToken) {
            formData.append("_draft_token", draftToken);
        }
        try {
            const response = await fetch(window.location.href, {
                method: "POST",
                body: formData,
                headers: {"X-Requested-With": "XMLHttpRequest"},
            });
            if (!response.ok) {
                console.error("Form draft autosave failed.");
                return;
            }
            const data = await response.json();
            if (registrationDraft && data.draft_token) {
                draftToken = data.draft_token;
                window.localStorage.setItem(draftStorageKey, draftToken);
                const draftUrl = new URL(window.location.href);
                draftUrl.searchParams.set("draft", draftToken);
                window.history.replaceState({}, "", draftUrl.toString());
            }
        } catch (error) {
            console.error("Form draft autosave failed.", error);
        }
    };

    const saveDraft = () => {
        if (draftSavePromise) {
            return draftSavePromise;
        }
        const operation = performDraftSave();
        draftSavePromise = operation.finally(() => {
            if (draftSavePromise) {
                draftSavePromise = null;
            }
        });
        return draftSavePromise;
    };

    const scheduleDraftSave = () => {
        if (!draftAutosaveEnabled || submissionInProgress) {
            return;
        }
        window.clearTimeout(draftSaveTimer);
        draftSaveTimer = window.setTimeout(saveDraft, 800);
    };

    form.addEventListener("input", (event) => {
        if (event.target.matches("input, select, textarea")) {
            updateChoiceFilters();
            updateCalculatedFields();
        }
        scheduleDraftSave();
    });
    form.addEventListener("change", scheduleDraftSave);

    const showGeneralMessage = (message, type = "error") => {
        const messageBox = document.createElement("div");
        messageBox.className =
            `submission-message submission-message-${type}`;
        messageBox.setAttribute("role", "alert");
        messageBox.textContent = message;

        form.prepend(messageBox);

        messageBox.scrollIntoView({
            behavior: "smooth",
            block: "center",
        });
    };

    const showFieldErrors = (errors) => {
        let firstInvalidField = null;

        Object.entries(errors).forEach(
            ([questionKey, message]) => {
                const match = questionKey.match(/^(\d+)(?:__repeat_(\d+))?$/);
                const questionId = match ? match[1] : questionKey;
                const repeatIndex = match?.[2] || "0";
                const step = form.querySelector(
                    `.wizard-step[data-repeat-index="${repeatIndex}"] [data-question-id="${questionId}"]`
                );
                const fieldWrapper = step || form.querySelector(`[data-question-id="${questionId}"]`);
                const errorElement = fieldWrapper?.querySelector(".field-error");

                if (fieldWrapper) {
                    fieldWrapper.classList.add("has-error");

                    if (!firstInvalidField) {
                        firstInvalidField = fieldWrapper;
                    }
                }

                if (errorElement) {
                    errorElement.textContent = message;
                    errorElement.classList.add("is-visible");
                }
            }
        );

        if (firstInvalidField) {
            firstInvalidField.scrollIntoView({
                behavior: "smooth",
                block: "center",
            });
        }
    };

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        clearErrors();

        if (!form.checkValidity()) {
            const steps = getVisibleSteps();
            const firstInvalid = form.querySelector(":invalid");
            const invalidStep = steps.findIndex(
                (step) => firstInvalid && step.contains(firstInvalid)
            );

            if (invalidStep >= 0) {
                showStep(invalidStep);
            }

            firstInvalid?.reportValidity();
            return;
        }

        submissionInProgress = true;
        window.clearTimeout(draftSaveTimer);

        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent =
                language === "en"
                    ? "Submitting..."
                    : "Inawasilisha...";
        }

        try {
            // Finish an autosave that started before Submit was clicked. This
            // ensures the final request receives its token and completes the
            // same record instead of leaving an orphan draft behind.
            if (draftSavePromise) {
                await draftSavePromise;
            }
            const formData = new FormData(form);
            if (draftToken) {
                formData.append("_draft_token", draftToken);
            }

            const response = await fetch(
                window.location.href,
                {
                    method: "POST",
                    body: formData,
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                }
            );

            const data = await response.json();

            if (!response.ok || !data.success) {
                if (data.duplicate && data.redirect_url) {
                    window.location.assign(data.redirect_url);
                    return;
                }

                showGeneralMessage(
                    data.message ||
                        (
                            language === "en"
                                ? "Please correct the form errors."
                                : "Tafadhali rekebisha makosa ya fomu."
                        )
                );

                if (data.errors) {
                    showFieldErrors(data.errors);

                    const firstErrorId = Object.keys(data.errors)[0];
                    const errorField = form.querySelector(
                        `[data-question-id="${firstErrorId}"]`
                    );
                    const errorStep = getVisibleSteps().findIndex(
                        (step) => errorField && step.contains(errorField)
                    );

                    if (errorStep >= 0) {
                        showStep(errorStep);
                    }
                }

                return;
            }

            showGeneralMessage(
                data.message ||
                    (
                        language === "en"
                            ? "Submission completed successfully."
                            : "Fomu imewasilishwa kwa mafanikio."
                    ),
                "success"
            );

            if (registrationDraft) {
                window.localStorage.removeItem(draftStorageKey);
            }

            window.location.assign(data.redirect_url);
        } catch (error) {
            console.error(error);

            showGeneralMessage(
                language === "en"
                    ? "The form could not be submitted. Please try again."
                    : "Fomu haikuweza kuwasilishwa. Tafadhali jaribu tena."
            );
        } finally {
            submissionInProgress = false;
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = originalButtonText;
            }
        }
    });
});
