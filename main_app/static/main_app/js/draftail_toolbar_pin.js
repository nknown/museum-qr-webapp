(function () {
    "use strict";

    // Wagtail 7.3 reads this preference when each Draftail editor mounts.
    // The --pin CSS class exists in both modes; it is not a visibility flag.
    function saveStickyPreference() {
        try {
            window.localStorage.setItem("wagtail:draftail-toolbar", "sticky");
        } catch (error) {
            // The toolbar event below also works when storage is unavailable.
        }
    }

    function pinToolbars() {
        saveStickyPreference();
        document.dispatchEvent(new CustomEvent("draftail:toolbar", {
            detail: { toolbar: "sticky" }
        }));
    }

    saveStickyPreference();
    var pending = false;
    function schedulePin() {
        if (pending) {
            return;
        }
        pending = true;
        window.setTimeout(function () {
            pending = false;
            pinToolbars();
        }, 0);
    }

    document.addEventListener("draftail:toolbar", function (event) {
        if (event.detail && event.detail.toolbar !== "sticky") {
            schedulePin();
        }
    });

    function watchEditors() {
        schedulePin();
        var observer = new MutationObserver(function (mutations) {
            var selector = ".Draftail-Editor, .Draftail-FloatingToolbar";
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType === Node.ELEMENT_NODE &&
                        (node.matches(selector) || node.querySelector(selector))) {
                        schedulePin();
                    }
                });
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", watchEditors, { once: true });
    } else {
        watchEditors();
    }
})();
