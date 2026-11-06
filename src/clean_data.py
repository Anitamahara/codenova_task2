"""
CodeNova Internship - Task 2: Data Cleaning Report
Dataset: UCI Online Retail

Run from the project folder:
    python src/clean_data.py
    python src/clean_data.py --input "data/raw/Online Retail.xlsx" --output outputs

The script follows six steps, and each step is one function below:
    Step 1  load_raw()          read the raw file as plain text, never change it
    Step 2  scan_raw()          measure missing values, duplicates, bad types
    Step 3  find_outliers()     find unusual numbers with IQR and Z-score
    Step 4  clean()             apply the cleaning rules, keep every removed row
    Step 5  build_comparison()  compare the data before and after
            write_report()      write the Data Quality Audit Report
    Step 6  main()              check the results, then stop if anything is wrong

Every number in the report is calculated from the data when the script runs.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # lets charts save to a file without opening a window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

EXPECTED_COLUMNS = [
    "InvoiceNo", "StockCode", "Description", "Quantity",
    "InvoiceDate", "UnitPrice", "CustomerID", "Country",
]

# Stock codes that are fees or service charges, not goods. They are listed here
# so that anyone reading the code can see exactly what is removed.
NON_PRODUCT_CODES = {
    "POST": "postage",
    "DOT": "dotcom postage",
    "M": "manual entry",
    "D": "discount",
    "S": "samples",
    "B": "bad debt adjustment",
    "C2": "carriage",
    "CRUK": "charity commission",
    "BANK CHARGES": "bank charges",
    "AMAZONFEE": "Amazon fee",
    "PADS": "padding (internal)",
}

COUNTRY_FIXES = {"EIRE": "Ireland", "RSA": "South Africa"}

# Plain-language reason shown for each removal rule in the report.
REASONS = {
    "unreadable_value": "Date, Quantity or UnitPrice could not be read as a valid value, so the row cannot be used in any calculation.",
    "exact_duplicate": "Every column matches an earlier row, so keeping it would count the same sale twice.",
    "cancelled_invoice": "Invoice number starts with C, which marks a cancellation and not a sale.",
    "zero_or_negative_price": "Price is 0 or below, so this is a stock adjustment or note and not a sale.",
    "not_positive_quantity": "Quantity is 0 or below on a non-cancelled invoice, so nothing was sold.",
    "non_product_code": "Stock code is a fee or service charge (see NON_PRODUCT_CODES), not goods.",
    "reversed_by_cancellation": "A later cancellation by the same customer undid exactly this item and quantity, so the sale never really stood.",
}

CHART_BLUE = "#2a78d6"
CHART_GRAY = "#8A8F98"


def file_hash(path):
    """Fingerprint of a file. If one byte changes, the fingerprint changes."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# Step 1
def load_raw(path):
    """Read everything as text so that pandas cannot silently change a value."""
    options = {"dtype": str, "keep_default_na": False, "na_values": [""]}
    if path.suffix.lower() in {".xlsx", ".xls"}:
        raw = pd.read_excel(path, **options)
    else:
        try:
            raw = pd.read_csv(path, encoding="utf-8", **options)
        except UnicodeDecodeError:
            raw = pd.read_csv(path, encoding="latin-1", **options)

    missing = [c for c in EXPECTED_COLUMNS if c not in raw.columns]
    if missing:
        sys.exit(f"Input file is missing these columns: {missing}")
    return raw[EXPECTED_COLUMNS].copy()


def parse_types(raw):
    """Turn the text columns into real numbers and dates. Bad values become NaN."""
    df = raw.copy()
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["UnitPrice"] = pd.to_numeric(df["UnitPrice"], errors="coerce")
    df["CustomerID"] = pd.to_numeric(df["CustomerID"], errors="coerce")
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce", format="mixed")
    return df


# Step 2
def scan_raw(raw, parsed):
    """Measure the problems without changing anything."""
    total = len(raw)
    invoice = raw["InvoiceNo"].astype("string").str.strip()
    is_cancel = invoice.str.upper().str.startswith("C").fillna(False).astype(bool)

    missing = pd.DataFrame({
        "missing_rows": raw.isna().sum(),
        "missing_percent": (raw.isna().mean() * 100).round(2),
        "data_type_after_parsing": parsed.dtypes.astype(str),
    })
    missing.index.name = "column"

    has_extra_spaces = {}
    for column in ["InvoiceNo", "StockCode", "Description", "Country"]:
        text = raw[column].dropna().astype("string")
        has_extra_spaces[column] = int((text != text.str.strip()).sum())

    stock = raw["StockCode"].dropna().astype("string").str.strip()
    desc = raw["Description"].dropna().astype("string").str.strip()

    known = raw["CustomerID"].notna()
    invoices_with_known = set(invoice[known].dropna())
    invoices_with_missing = set(invoice[~known].dropna())

    missing_desc = raw["Description"].isna()
    return {
        "rows": total,
        "columns": raw.shape[1],
        "missing": missing,
        "exact_duplicates": int(raw.duplicated().sum()),
        "bad_quantity": int((raw["Quantity"].notna() & parsed["Quantity"].isna()).sum()),
        "bad_price": int((raw["UnitPrice"].notna() & parsed["UnitPrice"].isna()).sum()),
        "bad_date": int((raw["InvoiceDate"].notna() & parsed["InvoiceDate"].isna()).sum()),
        "bad_customer": int((raw["CustomerID"].notna() & parsed["CustomerID"].isna()).sum()),
        "whole_number_quantity": bool(((parsed["Quantity"].dropna() % 1) == 0).all()),
        "cancelled_rows": int(is_cancel.sum()),
        "negative_quantity": int((parsed["Quantity"] < 0).sum()),
        "negative_quantity_not_cancelled": int(((parsed["Quantity"] < 0) & ~is_cancel).sum()),
        "zero_price": int((parsed["UnitPrice"] == 0).sum()),
        "negative_price": int((parsed["UnitPrice"] < 0).sum()),
        "extra_spaces": has_extra_spaces,
        "stock_codes_as_written": int(stock.nunique()),
        "stock_codes_ignoring_case": int(stock.str.upper().nunique()),
        "descriptions_as_written": int(desc.nunique()),
        "descriptions_ignoring_case": int(desc.str.upper().nunique()),
        "invoices_mixing_known_and_missing_customer": len(invoices_with_known & invoices_with_missing),
        "missing_description_rows": int(missing_desc.sum()),
        "missing_description_with_zero_price": int((missing_desc & (parsed["UnitPrice"] == 0)).sum()),
    }


# ---------------------------------------------------------------- Step 3
def find_outliers(series):
    """IQR is the main rule. Z-score is run too, so the two can be compared."""
    data = series.dropna()
    q1, q3 = data.quantile(0.25), data.quantile(0.75)
    iqr = q3 - q1
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    std = data.std()
    z_count = int((((data - data.mean()) / std).abs() > 3).sum()) if std > 0 else 0
    return {
        "q1": q1, "q3": q3, "iqr": iqr, "low": low, "high": high,
        "iqr_outliers": int(((data < low) | (data > high)).sum()),
        "z_outliers": z_count,
        "rows_checked": int(len(data)),
    }


# ---------------------------------------------------------------- Step 4
def standardize(parsed):
    """Fix how values are written. This step never removes a row."""
    df = parsed.copy()
    for column in ["InvoiceNo", "StockCode", "Description", "Country"]:
        df[column] = df[column].astype("string").str.strip()
    df["InvoiceNo"] = df["InvoiceNo"].str.upper()
    df["StockCode"] = df["StockCode"].str.upper()
    df["Description"] = df["Description"].str.upper().str.replace(r"\s+", " ", regex=True)
    df["Country"] = df["Country"].replace(COUNTRY_FIXES)
    df["CustomerID"] = df["CustomerID"].astype("Int64")
    return df


def find_reversed_sales(sales, cancellations):
    """Match each cancellation to the latest earlier sale of the same customer,
    stock code and quantity. Each sale can only be matched once."""
    candidates = {}
    known = sales[sales["CustomerID"].notna()].sort_values("InvoiceDate")
    for row in known.itertuples():
        key = (row.CustomerID, row.StockCode, row.Quantity)
        candidates.setdefault(key, []).append((row.InvoiceDate, row.Index))

    reversed_rows = []
    known_cancels = cancellations[cancellations["CustomerID"].notna()]
    for row in known_cancels.sort_values("InvoiceDate").itertuples():
        key = (row.CustomerID, row.StockCode, -row.Quantity)
        options = candidates.get(key, [])
        for position in range(len(options) - 1, -1, -1):
            if options[position][0] <= row.InvoiceDate:
                reversed_rows.append(options.pop(position)[1])
                break
    return reversed_rows


def clean(parsed):
    """Apply the rules in order. Each removed row keeps the reason it was removed."""
    df = standardize(parsed)
    removed_parts = []
    steps = []

    def remove(mask, reason):
        nonlocal df
        mask = mask.fillna(False).astype(bool)
        taken = df[mask].copy()
        taken["RemovalReason"] = reason
        removed_parts.append(taken)
        df = df[~mask]
        steps.append({
            "reason": reason,
            "rows_removed": int(mask.sum()),
            "rows_left": len(df),
            "value_removed": float((taken["Quantity"] * taken["UnitPrice"]).sum()),
        })

    remove(df["InvoiceDate"].isna() | df["Quantity"].isna() | df["UnitPrice"].isna(), "unreadable_value")
    remove(df.duplicated(subset=EXPECTED_COLUMNS, keep="first"), "exact_duplicate")

    is_cancel = df["InvoiceNo"].str.startswith("C").fillna(False).astype(bool)
    cancellations = df[is_cancel].copy()
    remove(is_cancel, "cancelled_invoice")

    remove(df["UnitPrice"] <= 0, "zero_or_negative_price")
    remove(df["Quantity"] <= 0, "not_positive_quantity")

    is_fee = df["StockCode"].isin(NON_PRODUCT_CODES) | df["StockCode"].str.match(r"^GIFT_")
    remove(is_fee, "non_product_code")

    reversed_index = find_reversed_sales(df, cancellations)
    remove(pd.Series(df.index.isin(reversed_index), index=df.index), "reversed_by_cancellation")

    # One name per stock code: use the name that appears most often.
    named = df[df["Description"].notna()]
    usual_name = (
        named.groupby(["StockCode", "Description"]).size().rename("n").reset_index()
        .sort_values(["StockCode", "n", "Description"], ascending=[True, False, True])
        .drop_duplicates("StockCode").set_index("StockCode")["Description"]
    )
    imputed_description = int(df["Description"].isna().sum())
    new_names = df["StockCode"].map(usual_name)
    renamed = int((new_names.notna() & df["Description"].notna() & (new_names != df["Description"])).sum())
    df["Description"] = new_names.fillna(df["Description"]).fillna("UNKNOWN PRODUCT")
    unknown_after = int((df["Description"] == "UNKNOWN PRODUCT").sum())

    df["Quantity"] = df["Quantity"].astype("int64")
    df["Revenue"] = (df["Quantity"] * df["UnitPrice"]).round(2)
    df["HasCustomerID"] = df["CustomerID"].notna()

    # Outliers are measured on the sales only, then marked and kept.
    outliers = {
        "Quantity": find_outliers(df["Quantity"]),
        "UnitPrice": find_outliers(df["UnitPrice"]),
    }
    df["IsQuantityOutlier"] = df["Quantity"] > outliers["Quantity"]["high"]
    df["IsPriceOutlier"] = df["UnitPrice"] > outliers["UnitPrice"]["high"]

    removed = pd.concat(removed_parts) if removed_parts else df.iloc[0:0]
    actions = {
        "imputed_description": imputed_description,
        "renamed_description": renamed,
        "unknown_description": unknown_after,
    }
    return df.sort_values(["InvoiceDate", "InvoiceNo"]), removed, pd.DataFrame(steps), outliers, actions


# ---------------------------------------------------------------- Step 5
def profile(df):
    """The same measurements for any version of the data."""
    revenue = df["Quantity"] * df["UnitPrice"]
    return {
        "Rows": len(df),
        "Total missing cells": int(df[EXPECTED_COLUMNS].isna().sum().sum()),
        "Missing Description": int(df["Description"].isna().sum()),
        "Missing CustomerID": int(df["CustomerID"].isna().sum()),
        "Exact duplicate rows": int(df[EXPECTED_COLUMNS].duplicated().sum()),
        "Rows with Quantity <= 0": int((df["Quantity"] <= 0).sum()),
        "Rows with UnitPrice <= 0": int((df["UnitPrice"] <= 0).sum()),
        "Quantity mean": round(df["Quantity"].mean(), 2),
        "Quantity median": round(df["Quantity"].median(), 2),
        "Quantity std": round(df["Quantity"].std(), 2),
        "Quantity min": df["Quantity"].min(),
        "Quantity max": df["Quantity"].max(),
        "UnitPrice mean": round(df["UnitPrice"].mean(), 2),
        "UnitPrice median": round(df["UnitPrice"].median(), 2),
        "UnitPrice std": round(df["UnitPrice"].std(), 2),
        "UnitPrice min": df["UnitPrice"].min(),
        "UnitPrice max": df["UnitPrice"].max(),
        "Total revenue": round(revenue.sum(), 2),
        "Unique invoices": int(df["InvoiceNo"].nunique()),
        "Unique stock codes": int(df["StockCode"].nunique()),
        "Unique customers": int(df["CustomerID"].nunique()),
        "Unique countries": int(df["Country"].nunique()),
    }


def build_comparison(parsed, clean_df):
    before_view = parsed.copy()
    for column in ["InvoiceNo", "StockCode", "Description", "Country"]:
        before_view[column] = before_view[column].astype("string")
    table = pd.DataFrame({
        "Before": pd.Series(profile(before_view), dtype=object),
        "After": pd.Series(profile(clean_df), dtype=object),
    })
    table.index.name = "Metric"
    return table


def number(value):
    if isinstance(value, (float, np.floating)):
        return f"{value:,.2f}"
    return f"{value:,}"


def markdown_table(frame):
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    line = "|" + "|".join(" --- " for _ in frame.columns) + "|"
    rows = [
        "| " + " | ".join(number(v) if not isinstance(v, str) else v for v in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join([header, line, *rows])


def percent(part, whole):
    return f"{part / whole * 100:.2f}%" if whole else "0.00%"


def bar_chart(labels, values, title, xlabel, path):
    order = np.argsort(values)
    labels = [labels[i] for i in order]
    values = [values[i] for i in order]
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(labels) + 1.6), dpi=200)
    ax.barh(labels, values, color=CHART_BLUE, height=0.55)
    ax.set_title(title, loc="left", fontsize=12)
    ax.set_xlabel(xlabel, fontsize=9, color="#555555")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#E6E6E6", linewidth=0.7)
    ax.set_axisbelow(True)
    top = max(values) if max(values) > 0 else 1
    ax.set_xlim(0, top * 1.18)
    for position, value in enumerate(values):
        ax.text(value + top * 0.01, position, f"{value:,.2f}".rstrip("0").rstrip("."),
                va="center", fontsize=8, color="#333333")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def distribution_chart(parsed, clean_df, path):
    """Prices and quantities are very lopsided, so the x-axis uses a log scale.
    Only values above zero can be drawn on a log scale."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), dpi=200)
    for ax, column in zip(axes, ["Quantity", "UnitPrice"]):
        before = parsed[column].dropna()
        before = before[before > 0]
        after = clean_df[column]
        bins = np.logspace(np.log10(before.min()), np.log10(before.max()), 40)
        ax.hist(before, bins=bins, color=CHART_GRAY, alpha=0.55, label="Before")
        ax.hist(after, bins=bins, histtype="step", color=CHART_BLUE, linewidth=1.6, label="After")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(f"{column} (values above 0)", loc="left", fontsize=11)
        ax.set_xlabel(f"{column} (log scale)", fontsize=9, color="#555555")
        ax.set_ylabel("Rows (log scale)", fontsize=9, color="#555555")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#E6E6E6", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_report(path, info, scan, outliers_before, outliers_after, steps, comparison, actions, clean_df):
    rows_before, rows_after = scan["rows"], len(clean_df)
    missing_id = int(scan["missing"].loc["CustomerID", "missing_rows"])
    guest_rows = int((~clean_df["HasCustomerID"]).sum())
    guest_revenue = float(clean_df.loc[~clean_df["HasCustomerID"], "Revenue"].sum())
    total_revenue = float(clean_df["Revenue"].sum())

    missing_table = scan["missing"].reset_index()[["column", "missing_rows", "missing_percent"]]
    missing_table.columns = ["Column", "Missing rows", "Missing %"]

    steps_table = steps.copy()
    steps_table["why"] = steps_table["reason"].map(REASONS)
    steps_table = steps_table[["reason", "rows_removed", "rows_left", "value_removed", "why"]]
    steps_table.columns = ["Rule", "Rows removed", "Rows left", "Sales value of removed rows", "Why"]

    outlier_rows = []
    for stage, group in [("Before cleaning", outliers_before), ("After cleaning", outliers_after)]:
        for column, stats in group.items():
            outlier_rows.append({
                "Stage": stage, "Column": column,
                "Lower limit": float(stats["low"]), "Upper limit": float(stats["high"]),
                "IQR outliers": stats["iqr_outliers"],
                "IQR %": percent(stats["iqr_outliers"], stats["rows_checked"]),
                "Z-score outliers (over 3 std)": stats["z_outliers"],
            })
    outlier_table = pd.DataFrame(outlier_rows)

    flagged = clean_df["IsQuantityOutlier"] | clean_df["IsPriceOutlier"]
    flagged_revenue = float(clean_df.loc[flagged, "Revenue"].sum())

    comparison_view = comparison.reset_index()
    spaces = ", ".join(f"{k}: {v:,}" for k, v in scan["extra_spaces"].items())
    if scan["invoices_mixing_known_and_missing_customer"] == 0:
        customer_evidence = (
            "No invoice contains both a known and a missing CustomerID, so the ID "
            "cannot be recovered from other rows of the same invoice."
        )
    else:
        customer_evidence = (
            f"{scan['invoices_mixing_known_and_missing_customer']:,} invoices contain both known "
            "and missing IDs. This script does not fill those in, because that needs a manual check."
        )

    text = f"""# Data Quality Audit Report

**Project:** CodeNova Data Science Internship, Batch 01, Task 2
**Dataset:** UCI Online Retail, read from `{info['input_name']}`
**Raw file SHA-256:** `{info['hash']}`

This report is written by `src/clean_data.py`. Every number comes from the run that produced it.

## 1. Summary

- Rows went from **{rows_before:,}** to **{rows_after:,}**, so {rows_before - rows_after:,} rows ({percent(rows_before - rows_after, rows_before)}) were removed.
- Every removed row is saved with its reason in `outputs/removed_rows.csv`.
- The raw file was only read. Its SHA-256 fingerprint is the same before and after the run.
- {guest_rows:,} sales rows with no CustomerID are kept, because they are real sales. They make up {percent(guest_revenue, total_revenue)} of cleaned revenue.

## 2. What the scan found

Rows: {scan['rows']:,}. Columns: {scan['columns']}.

### Missing values

{markdown_table(missing_table)}

![Missing values](charts/missing_values.png)

### Duplicates and invalid data types

| Check | Result |
| --- | --- |
| Exact duplicate rows | {scan['exact_duplicates']:,} |
| Quantity values that are not numbers | {scan['bad_quantity']:,} |
| UnitPrice values that are not numbers | {scan['bad_price']:,} |
| InvoiceDate values that are not dates | {scan['bad_date']:,} |
| CustomerID values that are not numbers | {scan['bad_customer']:,} |
| Cancelled rows (invoice starts with C) | {scan['cancelled_rows']:,} |
| Rows with negative Quantity | {scan['negative_quantity']:,} |
| Negative Quantity on rows that are not cancelled | {scan['negative_quantity_not_cancelled']:,} |
| Rows with UnitPrice of 0 | {scan['zero_price']:,} |
| Rows with negative UnitPrice | {scan['negative_price']:,} |
| Stock codes as written / ignoring case | {scan['stock_codes_as_written']:,} / {scan['stock_codes_ignoring_case']:,} |
| Descriptions as written / ignoring case | {scan['descriptions_as_written']:,} / {scan['descriptions_ignoring_case']:,} |

Values with extra spaces at either end: {spaces}.

Data types: InvoiceNo is text because of the C prefix. InvoiceDate was parsed to a date. CustomerID is stored as a whole number that allows blanks, so `17850.0` becomes `17850`.

## 3. Outlier detection

The main method is IQR. Lower limit = Q1 - 1.5 x IQR. Upper limit = Q3 + 1.5 x IQR. The Z-score count is shown for comparison.

{markdown_table(outlier_table)}

**Decision: mark outliers, do not delete them.** A large quantity is often a real wholesale order and a high price is often an expensive product. After cleaning, the outlier rows hold {percent(flagged_revenue, total_revenue)} of revenue ({flagged_revenue:,.2f}), so deleting them would remove real business. They are marked in `IsQuantityOutlier` and `IsPriceOutlier`, so a later analysis can include or leave them out. Only the upper limit is used for the marks, because after cleaning all values are above zero.

The extreme values that were wrong were handled by a rule with evidence, `reversed_by_cancellation`. It removes a sale only when a later cancellation matches its customer, stock code and quantity.

## 4. Cleaning steps

### Changes that keep the row

| Change | Why |
| --- | --- |
| Removed extra spaces, made InvoiceNo, StockCode and Description upper case | The same value written two ways would be counted as two values. |
| Replaced EIRE with Ireland and RSA with South Africa | Plain country names, one name per country. |
| One Description per StockCode, the most common name (rows renamed: {actions['renamed_description']:,}) | The same product should group together in later analysis. |
| Added Revenue = Quantity x UnitPrice | Needed for sales analysis. |
| Added HasCustomerID and the two outlier marks | Lets later work filter without losing rows. |

### Removal rules, in the order they run

{markdown_table(steps_table)}

The rows are checked in this order and each removed row gets the first rule that matched, so no row is counted twice.

### Missing value decisions

**Description ({scan['missing_description_rows']:,} missing in raw data).** {scan['missing_description_with_zero_price']:,} of these rows had a UnitPrice of 0, so the price rule handles them. {actions['imputed_description']:,} rows reached the imputation step and were filled with the most common name for the same StockCode. {actions['unknown_description']:,} rows had no name to borrow and were labelled UNKNOWN PRODUCT.

**CustomerID ({missing_id:,} missing in raw data).** Not imputed. A customer ID identifies a person, so a mean or a guess would invent a customer and join their purchases to someone else. {customer_evidence} The rows stay in the main file with `HasCustomerID = False`. `outputs/online_retail_clean_customers.csv` holds only rows with an ID, for customer analysis.

## 5. Before and after

{markdown_table(comparison_view)}

![Before and after distributions](charts/distribution_before_after.png)

![Rows removed by rule](charts/rows_removed.png)

## 6. Limitations

- Exact duplicates may include a few real repeat scans of one item on one invoice. The data cannot separate those from double entries, so all exact copies are removed.
- `reversed_by_cancellation` only catches cancellations with an exact quantity match and a known customer. Partial cancellations are not matched.
- `NON_PRODUCT_CODES` is a hand-written list, so a new code in a later file would need adding.
- Revenue is in the currency of the source data and is not adjusted for tax or discounts.
"""
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- Step 6
def main():
    parser = argparse.ArgumentParser(description="Clean the Online Retail dataset.")
    parser.add_argument("--input", default="data/raw/Online Retail.xlsx")
    parser.add_argument("--output", default="outputs")
    args = parser.parse_args()

    input_path, output_dir = Path(args.input), Path(args.output)
    if not input_path.exists():
        sys.exit(f"Raw file not found: {input_path}\nPut the dataset in data/raw/ first.")
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    hash_before = file_hash(input_path)
    print("Step 1: loading the raw file")
    raw = load_raw(input_path)
    parsed = parse_types(raw)

    print("Step 2: scanning for problems")
    scan = scan_raw(raw, parsed)
    scan["missing"].to_csv(output_dir / "missing_values_scan.csv")

    print("Step 3: checking outliers before cleaning")
    outliers_before = {c: find_outliers(parsed[c]) for c in ["Quantity", "UnitPrice"]}

    print("Step 4: cleaning")
    clean_df, removed, steps, outliers_after, actions = clean(parsed)
    clean_df.to_csv(output_dir / "online_retail_clean.csv", index=False)
    clean_df[clean_df["HasCustomerID"]].to_csv(output_dir / "online_retail_clean_customers.csv", index=False)
    removed.to_csv(output_dir / "removed_rows.csv", index_label="RawRowIndex")

    print("Step 5: writing the comparison, charts and report")
    comparison = build_comparison(parsed, clean_df)
    comparison.to_csv(output_dir / "before_after_comparison.csv")

    bar_chart(list(scan["missing"].index), [float(v) for v in scan["missing"]["missing_percent"]],
              "Missing values by column", "Percent of rows", chart_dir / "missing_values.png")
    bar_chart(list(steps["reason"]), [int(v) for v in steps["rows_removed"]],
              "Rows removed by rule", "Rows", chart_dir / "rows_removed.png")
    distribution_chart(parsed, clean_df, chart_dir / "distribution_before_after.png")

    print("Step 6: checking the results")
    hash_after = file_hash(input_path)
    if hash_before != hash_after:
        sys.exit("STOPPED: the raw file changed during the run.")
    if len(raw) != len(clean_df) + len(removed):
        sys.exit("STOPPED: clean rows + removed rows does not equal raw rows.")
    if clean_df[EXPECTED_COLUMNS].duplicated().any():
        sys.exit("STOPPED: duplicates are left in the clean data.")
    if (clean_df["Quantity"] <= 0).any() or (clean_df["UnitPrice"] <= 0).any():
        sys.exit("STOPPED: invalid quantities or prices are left in the clean data.")

    write_report(output_dir / "Data_Quality_Audit_Report.md",
                 {"input_name": input_path.name, "hash": hash_before},
                 scan, outliers_before, outliers_after, steps, comparison, actions, clean_df)

    print(f"\nDone. {len(raw):,} raw rows = {len(clean_df):,} clean + {len(removed):,} removed")
    print("All checks passed. The report is in", output_dir / "Data_Quality_Audit_Report.md")


if __name__ == "__main__":
    main()
