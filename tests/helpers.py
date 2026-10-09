def formset_data(prefix, rows, initial=0):
    """POST data for a principal formset.

    Each row is `(principal, permission)` or `(principal, permission, True)` to delete it.
    `initial` is how many of the rows the form was first rendered with.
    """
    data = {f"{prefix}-TOTAL_FORMS": len(rows), f"{prefix}-INITIAL_FORMS": initial}
    for index, row in enumerate(rows):
        data[f"{prefix}-{index}-principal"] = row[0]
        data[f"{prefix}-{index}-permission"] = row[1]
        if len(row) > 2 and row[2]:
            data[f"{prefix}-{index}-DELETE"] = "on"
    return data
