document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("dynamic-event-form");

    if (!form) {
        return;
    }

    const submitButton = form.querySelector(".submit-button");
    const allSteps = Array.from(form.querySelectorAll(".wizard-step"));
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
        Object.entries(draftAnswers).forEach(([questionId, storedValue]) => {
            const values = Array.isArray(storedValue)
                ? storedValue.map(String)
                : [String(storedValue)];
            form.querySelectorAll(`[name="question_${questionId}"]`)
                .forEach((control) => {
                    if (control.type === "checkbox" || control.type === "radio") {
                        control.checked = values.includes(control.value);
                    } else if (control.type !== "file") {
                        control.value = values[0] || "";
                    }
                });
        });
    };

    restoreDraftAnswers();

    allSteps.forEach((step) => {
        step.querySelectorAll("input, select, textarea").forEach((control) => {
            control.dataset.originalRequired = control.required ? "true" : "false";
        });
    });

    const answerValues = (questionId) => Array.from(
        form.querySelectorAll(`[name="question_${questionId}"]`)
    ).filter((control) => !control.disabled).flatMap((control) => {
        if (control.type === "checkbox" || control.type === "radio") {
            return control.checked ? [control.value.trim()] : [];
        }
        return control.value.trim() ? [control.value.trim()] : [];
    });

    const ruleMatches = (rule) => {
        const values = answerValues(rule.question);
        const expected = String(rule.value || "");
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
        case "ANY_OF": return values.some((value) => (rule.values || []).map(String).includes(value));
        case "NONE_OF": return !values.some((value) => (rule.values || []).map(String).includes(value));
        case "GREATER_THAN": {
            const actualNumber = Number(values[0]);
            const expectedNumber = Number(expected);
            return values.length > 0 && Number.isFinite(actualNumber) &&
                Number.isFinite(expectedNumber) && actualNumber > expectedNumber;
        }
        case "LESS_THAN": {
            const actualNumber = Number(values[0]);
            const expectedNumber = Number(expected);
            return values.length > 0 && Number.isFinite(actualNumber) &&
                Number.isFinite(expectedNumber) && actualNumber < expectedNumber;
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
        const results = (logic.rules || []).map(ruleMatches);
        if (!results.length) {
            return true;
        }
        return logic.match === "ANY" ? results.some(Boolean) : results.every(Boolean);
    };

    const getVisibleSteps = () => allSteps.filter(conditionMatches);

    const applyConditionalState = () => {
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
        const unansweredRequiredGroup = Array.from(
            step.querySelectorAll(
                '.form-field[data-required="true"][data-question-type="MULTIPLE_CHOICE"]'
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

        applyConditionalState();
        rebuildStepDots();

        form.addEventListener("change", (event) => {
            if (!event.target.matches("input, select, textarea")) {
                return;
            }

            event.target.closest(".form-field")
                ?.querySelectorAll("input, select, textarea")
                .forEach((control) => control.setCustomValidity(""));
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

    form.addEventListener("input", scheduleDraftSave);
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
            ([questionId, message]) => {
                const fieldWrapper = form.querySelector(
                    `[data-question-id="${questionId}"]`
                );

                const errorElement = document.getElementById(
                    `error-question-${questionId}`
                );

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
