// Add and remove rows in a Django formset.
//
// Expected markup, all inside one element:
//   [data-formset data-formset-prefix="<prefix>"]   the container, holding the management form
//   [data-formset-rows]                             where rows live
//   template[data-formset-template]                 the formset's empty_form, containing __prefix__
//   [data-formset-add]                              button that appends a row
// and inside each [data-formset-row]:
//   input[name$="-DELETE"]                          Django's delete checkbox
//   [data-formset-delete-fallback]                  wrapper around that checkbox, hidden here
//   [data-formset-delete]                           button that removes the row
//
// Removed rows stay in the DOM, hidden and flagged for deletion, so indexes never need renumbering.
(function () {
  "use strict";

  function setUpRow(row) {
    var checkbox = row.querySelector('input[name$="-DELETE"]');
    var fallback = row.querySelector("[data-formset-delete-fallback]");
    var button = row.querySelector("[data-formset-delete]");
    if (!checkbox || !button) {
      return;
    }
    if (fallback) {
      fallback.classList.add("d-none");
    }
    button.classList.remove("d-none");
    if (checkbox.checked) {
      row.classList.add("d-none");
    }
    button.addEventListener("click", function () {
      checkbox.checked = true;
      row.classList.add("d-none");
    });
  }

  function setUpFormset(container) {
    var prefix = container.dataset.formsetPrefix;
    var rows = container.querySelector("[data-formset-rows]");
    var template = container.querySelector("template[data-formset-template]");
    var addButton = container.querySelector("[data-formset-add]");
    var totalForms = container.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]');

    rows.querySelectorAll("[data-formset-row]").forEach(setUpRow);

    addButton.addEventListener("click", function () {
      var index = parseInt(totalForms.value, 10);
      var holder = document.createElement("div");
      holder.innerHTML = template.innerHTML.replace(/__prefix__/g, String(index));
      var row = holder.querySelector("[data-formset-row]");
      rows.appendChild(row);
      totalForms.value = String(index + 1);
      setUpRow(row);
      var firstField = row.querySelector("select, input:not([type=checkbox])");
      if (firstField) {
        firstField.focus();
      }
    });
  }

  document.querySelectorAll("[data-formset]").forEach(setUpFormset);
})();
