"""Selection logic independent of Odoo and of estimated row heights."""


def select_first_page(row_count, fits, is_heading=lambda index: False):
    """Find a fitting row prefix using the real renderer as an oracle.

    Returning zero is valid when the addresses and legal footer leave no
    space for a full item. No invoice line is split or discarded here.
    """
    if row_count < 0:
        raise ValueError("row_count must be non-negative")
    if not fits(0):
        raise ValueError("The first-page header and footer do not fit on one page")
    low, high = 0, row_count
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    # Do not leave a new section heading on the first page without its items.
    while low and is_heading(low - 1):
        low -= 1
    # Column widths can change when a table is split. Validate the chosen
    # candidate rather than assuming that all heights are monotonic.
    while low and not fits(low):
        low -= 1
        while low and is_heading(low - 1):
            low -= 1
    return low
