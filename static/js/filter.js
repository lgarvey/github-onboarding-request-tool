// Search and page through a long list.
//
// Expected markup:
//   [data-filter data-filter-list="<id of the list>"]   the wrapper, hidden until this runs
//     input[data-filter-input]                           the search box
//     [data-filter-count data-filter-noun="<plural>"]    where "Showing 1 to 25 of 413 <plural>" goes
//     optional data-filter-page-size                     items per page, 25 if not given
// and each item in the list has data-filter-text, the lower-case text to match against.
//
// Every word typed must appear somewhere in an item's text, in any order. Previous and Next
// buttons are added after the list when the matches do not fit on one page. Without
// JavaScript the whole list is shown.
(function () {
  "use strict";

  function button(label) {
    var element = document.createElement("button");
    element.type = "button";
    element.className = "btn btn-sm btn-outline-secondary";
    element.textContent = label;
    return element;
  }

  function setUp(wrapper) {
    var list = document.getElementById(wrapper.dataset.filterList);
    var input = wrapper.querySelector("[data-filter-input]");
    var count = wrapper.querySelector("[data-filter-count]");
    if (!list || !input || !count) {
      return;
    }
    var items = Array.prototype.slice.call(list.querySelectorAll("[data-filter-text]"));
    var pageSize = parseInt(wrapper.dataset.filterPageSize, 10) || 25;
    var noun = count.dataset.filterNoun;
    var matches = items;
    var page = 0;

    var pager = document.createElement("nav");
    pager.className = "d-flex align-items-center gap-2 mb-3";
    pager.setAttribute("aria-label", "Pages of " + noun);
    var previous = button("Previous");
    var next = button("Next");
    var position = document.createElement("span");
    position.className = "text-muted small";
    pager.appendChild(previous);
    pager.appendChild(position);
    pager.appendChild(next);
    list.insertAdjacentElement("afterend", pager);

    function show() {
      var pages = Math.max(1, Math.ceil(matches.length / pageSize));
      page = Math.min(Math.max(page, 0), pages - 1);
      var first = page * pageSize;
      var last = Math.min(first + pageSize, matches.length);
      var visible = matches.slice(first, last);
      items.forEach(function (item) {
        var shown = visible.indexOf(item) !== -1;
        // Bootstrap's d-flex is !important, so the hidden attribute alone would not hide a row.
        item.classList.toggle("d-none", !shown);
        item.classList.toggle("d-flex", shown);
      });
      list.classList.toggle("d-none", matches.length === 0);
      pager.classList.toggle("d-none", pages === 1);
      pager.classList.toggle("d-flex", pages > 1);
      previous.disabled = page === 0;
      next.disabled = page === pages - 1;
      position.textContent = "Page " + (page + 1) + " of " + pages;

      var searching = matches !== items;
      if (matches.length === 0) {
        count.textContent = "No " + noun + " match.";
      } else if (pages === 1 && !searching) {
        count.textContent = "";
      } else {
        var range = pages === 1 ? String(matches.length) : first + 1 + " to " + last + " of " + matches.length;
        count.textContent = "Showing " + range + " " + noun + (searching ? " matching your search." : ".");
      }
    }

    function search() {
      var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
      matches = !words.length
        ? items
        : items.filter(function (item) {
            return words.every(function (word) {
              return item.dataset.filterText.indexOf(word) !== -1;
            });
          });
      page = 0;
      show();
    }

    input.addEventListener("input", search);
    previous.addEventListener("click", function () {
      page -= 1;
      show();
    });
    next.addEventListener("click", function () {
      page += 1;
      show();
    });
    wrapper.classList.remove("d-none");
    // The browser may restore what was typed when you come back to the page.
    search();
  }

  document.querySelectorAll("[data-filter]").forEach(setUp);
})();
