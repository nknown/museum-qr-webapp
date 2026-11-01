(function () {
    "use strict";

    var EDITOR_SELECTOR = ".Draftail-Editor";
    var TOOLBAR_SELECTOR = ".Draftail-Toolbar";
    var PIN_BUTTON_SELECTOR = ".Draftail-ToolbarButton--pin";

    function ensurePinned(editor) {
        if (!editor || editor.dataset.defaultPinAttempted === "1") {
            return;
        }

        var toolbar = editor.querySelector(TOOLBAR_SELECTOR);
        if (!toolbar || toolbar.classList.contains("Draftail-Toolbar--pin")) {
            return;
        }

        editor.dataset.defaultPinAttempted = "1";

        var pinButton = editor.querySelector(PIN_BUTTON_SELECTOR);
        if (pinButton && !pinButton.disabled) {
            pinButton.click();
        }

        // Fallback for future Draftail changes where button click does not toggle class.
        if (!toolbar.classList.contains("Draftail-Toolbar--pin")) {
            toolbar.classList.add("Draftail-Toolbar--pin");
        }
    }

    function scanForEditors(root) {
        if (!root) {
            return;
        }

        if (root.matches && root.matches(EDITOR_SELECTOR)) {
            ensurePinned(root);
        }

        if (!root.querySelectorAll) {
            return;
        }

        var editors = root.querySelectorAll(EDITOR_SELECTOR);
        editors.forEach(ensurePinned);
    }

    document.addEventListener("DOMContentLoaded", function () {
        scanForEditors(document);

        document.addEventListener(
            "focusin",
            function (event) {
                if (!event.target || !event.target.closest) {
                    return;
                }

                var editor = event.target.closest(EDITOR_SELECTOR);
                if (!editor) {
                    return;
                }

                window.requestAnimationFrame(function () {
                    ensurePinned(editor);
                });
            },
            true
        );

        var observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        scanForEditors(node);
                    }
                });
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });
    });
})();
