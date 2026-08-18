document.addEventListener("DOMContentLoaded", function () {
    const programme = document.querySelector(".conference-programme-page");

    if (!programme) {
        return;
    }

    const tabs = Array.from(
        programme.querySelectorAll("[data-programme-session]")
    );
    const panels = Array.from(
        programme.querySelectorAll(".conference-programme-session")
    );
    const printButton = programme.querySelector("[data-print-timetable]");
    const downloadButton = programme.querySelector("[data-download-timetable]");

    function selectedPanels() {
        return panels.filter(function (panel) {
            return !panel.hidden;
        });
    }

    function updateActions() {
        const hasSelection = selectedPanels().length > 0;

        if (printButton) {
            printButton.disabled = !hasSelection;
        }
        if (downloadButton) {
            downloadButton.disabled = !hasSelection;
        }
    }

    function toggleSession(button) {
        const panel = programme.querySelector(
            "#" + button.dataset.programmeSession
        );
        const isSelected = button.getAttribute("aria-pressed") === "true";

        button.setAttribute("aria-pressed", String(!isSelected));
        panel.hidden = isSelected;
        updateActions();
    }

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            toggleSession(tab);
        });

        tab.addEventListener("keydown", function (event) {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
                return;
            }

            event.preventDefault();
            const direction = event.key === "ArrowRight" ? 1 : -1;
            const currentIndex = tabs.indexOf(tab);
            const nextIndex = (currentIndex + direction + tabs.length) % tabs.length;

            tabs[nextIndex].focus();
        });
    });

    const requestedSessions = new URLSearchParams(window.location.search).getAll(
        "session"
    );
    requestedSessions.forEach(function (sessionId) {
        const tab = programme.querySelector(
            '[data-programme-session="session-' + CSS.escape(sessionId) + '"]'
        );
        if (tab && tab.getAttribute("aria-pressed") !== "true") {
            toggleSession(tab);
        }
    });

    if (printButton) {
        printButton.addEventListener("click", function () {
            window.print();
        });
    }

    if (downloadButton) {
        downloadButton.addEventListener("click", function () {
            const url = new URL(downloadButton.dataset.downloadUrl, window.location.origin);

            selectedPanels().forEach(function (panel) {
                url.searchParams.append("session", panel.id.replace("session-", ""));
            });

            window.location.assign(url.toString());
        });
    }

    updateActions();

    window.addEventListener("beforeprint", function () {
        const printablePanels = selectedPanels();

        panels.forEach(function (panel) {
            panel.classList.remove("is-print-last");
        });

        if (printablePanels.length) {
            printablePanels[printablePanels.length - 1].classList.add(
                "is-print-last"
            );
        }
    });

    window.addEventListener("afterprint", function () {
        panels.forEach(function (panel) {
            panel.classList.remove("is-print-last");
        });
    });
});

