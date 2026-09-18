from pathlib import Path
from datetime import datetime
import json
import math
import re

import pandas as pd


DOMAIN_FILES = [
    "DM",
    "AE",
    "LB",
    "VS",
    "EX",
    "CM",
    "DS",
    "MH",
    "EG",
]

SEQUENCE_COLUMNS = {
    "DM": None,
    "AE": "AESEQ",
    "LB": "LBSEQ",
    "VS": "VSSEQ",
    "EX": "EXSEQ",
    "CM": "CMSEQ",
    "DS": "DSSEQ",
    "MH": "MHSEQ",
    "EG": "EGSEQ",
}

DATE_COLUMNS = {
    "DM": ["BRTHDTC", "RFSTDTC"],
    "AE": ["AESTDTC", "AEENDTC"],
    "LB": ["LBDTC"],
    "VS": ["VSDTC"],
    "EX": ["EXSTDTC"],
    "CM": ["CMSTDTC"],
    "DS": ["DSSTDTC"],
    "MH": [],
    "EG": ["EGDTC"],
}

LAB_CONVERSIONS = {
    ("ALT", "ukat/l"): ("U/L", 60.0),
    ("ALT", "µkat/l"): ("U/L", 60.0),
    ("ALT", "μkat/l"): ("U/L", 60.0),
    ("AST", "ukat/l"): ("U/L", 60.0),
    ("AST", "µkat/l"): ("U/L", 60.0),
    ("AST", "μkat/l"): ("U/L", 60.0),
}


def clean_string(value):
    if pd.isna(value):
        return None

    text = str(value).strip()

    if text == "":
        return None

    return text


def parse_date(value):
    if pd.isna(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    parsed = pd.to_datetime(text, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.strftime("%Y-%m-%d")


def parse_lab_value(value):
    """
    Returns:
        {
            "value": numeric value or None,
            "status": normal / below_detection / not_detected /
                      missing / invalid
        }
    """

    if pd.isna(value):
        return None, "missing"

    text = str(value).strip()

    if text == "":
        return None, "missing"

    upper = text.upper()

    if upper == "ND":
        return None, "not_detected"

    if text.startswith("<"):
        number_text = text[1:].strip()

        try:
            number = float(number_text.replace(",", "."))
            return number, "below_detection"
        except ValueError:
            return None, "invalid"

    if text.startswith(">"):
        number_text = text[1:].strip()

        try:
            number = float(number_text.replace(",", "."))
            return number, "above_detection"
        except ValueError:
            return None, "invalid"

    text = text.replace(",", ".")

    try:
        number = float(text)

        if math.isnan(number):
            return None, "missing"

        return number, "normal"

    except ValueError:
        return None, "invalid"


class StudyGraph:

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

        if not self.data_dir.exists():
            raise FileNotFoundError(
                f"Data directory does not exist: {self.data_dir}"
            )

        self.raw = {}
        self.data = {}

        self.cuts = pd.DataFrame()
        self.reference_ranges = pd.DataFrame()
        self.corrections = pd.DataFrame()

        self.nodes = {}
        self.edges = []

        self.subject_index = {}
        self.record_index = {}

        self.current_cut = None
        self.protocol_version = None

        self._load_static_files()

    # ---------------------------------------------------------
    # FILE LOADING
    # ---------------------------------------------------------

    def _find_data_path(self, filename):
        direct = self.data_dir / filename

        if direct.exists():
            return direct

        matches = list(self.data_dir.rglob(filename))

        if matches:
            return matches[0]

        return None

    def _load_csv(self, filename):
        path = self._find_data_path(filename)

        if path is None:
            raise FileNotFoundError(
                f"Required file not found: {filename}"
            )

        return pd.read_csv(path)

    def _load_static_files(self):

        cuts_path = self._find_data_path("cuts.csv")

        if cuts_path is not None:
            self.cuts = pd.read_csv(cuts_path)

        ref_path = self._find_data_path("reference_ranges.csv")

        if ref_path is not None:
            self.reference_ranges = pd.read_csv(ref_path)

        corrections_path = self._find_data_path("corrections.csv")

        if corrections_path is not None:
            self.corrections = pd.read_csv(corrections_path)

        for domain in DOMAIN_FILES:

            path = self._find_data_path(f"{domain}.csv")

            if path is None:
                continue

            self.raw[domain] = pd.read_csv(path)

    # ---------------------------------------------------------
    # CUT / PROTOCOL
    # ---------------------------------------------------------

    def _latest_cut(self):

        if self.cuts.empty:
            return 1

        if "cut" not in self.cuts.columns:
            return 1

        return int(self.cuts["cut"].max())

    def _protocol_for_cut(self, cut):

        if self.cuts.empty:
            return None

        if "cut" not in self.cuts.columns:
            return None

        available = self.cuts[self.cuts["cut"] <= cut]

        if available.empty:
            return None

        latest = available.sort_values("cut").iloc[-1]

        if "protocol_version" in latest:
            return int(latest["protocol_version"])

        return None

    # ---------------------------------------------------------
    # FILTER DATA TO CUT
    # ---------------------------------------------------------

    def _filter_to_cut(self, df, cut):

        if df is None or df.empty:
            return pd.DataFrame()

        result = df.copy()

        if "cut_available" in result.columns:

            result["cut_available"] = pd.to_numeric(
                result["cut_available"],
                errors="coerce"
            )

            result = result[
                result["cut_available"].fillna(0) <= cut
            ]

        return result.reset_index(drop=True)

    # ---------------------------------------------------------
    # APPLY CORRECTIONS
    # ---------------------------------------------------------

    def _apply_corrections(self, domain, df, cut):

        if df.empty:
            return df

        if self.corrections.empty:
            return df

        corrections = self.corrections.copy()

        required = {
            "cut",
            "domain",
            "usubjid",
            "seq",
            "field",
            "old_value",
            "new_value",
        }

        if not required.issubset(corrections.columns):
            return df

        corrections["cut"] = pd.to_numeric(
            corrections["cut"],
            errors="coerce"
        )

        corrections = corrections[
            (corrections["cut"] <= cut)
            & (corrections["domain"].astype(str) == domain)
        ]

        if corrections.empty:
            return df

        result = df.copy()

        seq_column = SEQUENCE_COLUMNS.get(domain)

        for _, correction in corrections.iterrows():

            usubjid = clean_string(correction["usubjid"])

            if not usubjid:
                continue

            field = clean_string(correction["field"])

            if not field or field not in result.columns:
                continue

            if seq_column is None:
                mask = (
                    result["USUBJID"].astype(str)
                    == str(usubjid)
                )
            else:
                seq = correction["seq"]

                mask = (
                    result["USUBJID"].astype(str)
                    == str(usubjid)
                ) & (
                    result[seq_column].astype(str)
                    == str(seq)
                )

            if not mask.any():
                continue

            new_value = correction["new_value"]

            result.loc[mask, field] = new_value

        return result

    # ---------------------------------------------------------
    # REFERENCE RANGE
    # ---------------------------------------------------------

    def _reference_for_lab(self, test_code, unit):

        if self.reference_ranges.empty:
            return None

        refs = self.reference_ranges.copy()

        if "LBTESTCD" not in refs.columns:
            return None

        refs = refs[
            refs["LBTESTCD"].astype(str).str.upper()
            == str(test_code).upper()
        ]

        if unit is not None and "LBORRESU" in refs.columns:

            matching_unit = refs[
                refs["LBORRESU"].astype(str).str.lower()
                == str(unit).lower()
            ]

            if not matching_unit.empty:
                refs = matching_unit

        if refs.empty:
            return None

        row = refs.iloc[0]

        low = None
        high = None

        if "LOW" in refs.columns:
            try:
                low = float(row["LOW"])
            except (ValueError, TypeError):
                pass

        if "HIGH" in refs.columns:
            try:
                high = float(row["HIGH"])
            except (ValueError, TypeError):
                pass

        return {
            "low": low,
            "high": high,
            "unit": clean_string(
                row["LBORRESU"]
            ) if "LBORRESU" in refs.columns else unit,
            "lab": clean_string(
                row["LAB"]
            ) if "LAB" in refs.columns else None,
        }

    # ---------------------------------------------------------
    # NORMALIZE LAB
    # ---------------------------------------------------------

    def _normalize_lab_row(self, row):

        test_code = clean_string(row.get("LBTESTCD"))
        original_unit = clean_string(row.get("LBORRESU"))
        original_value = row.get("LBORRES")

        numeric_value, status = parse_lab_value(
            original_value
        )

        normalized_unit = original_unit

        if test_code and original_unit:

            key = (
                test_code.upper(),
                original_unit.lower()
            )

            if key in LAB_CONVERSIONS:

                normalized_unit, multiplier = (
                    LAB_CONVERSIONS[key]
                )

                if numeric_value is not None:
                    numeric_value *= multiplier

        ref = self._reference_for_lab(
            test_code,
            normalized_unit
        )

        low = None
        high = None

        if ref is not None:
            low = ref["low"]
            high = ref["high"]

        result = row.copy()

        result["LB_VALUE"] = numeric_value
        result["LB_VALUE_STATUS"] = status
        result["LB_NORMALIZED_UNIT"] = normalized_unit
        result["LB_LOW"] = low
        result["LB_HIGH"] = high

        return result

    # ---------------------------------------------------------
    # SITE
    # ---------------------------------------------------------

    def _site_from_usubjid(self, usubjid):

        if not usubjid:
            return None

        text = str(usubjid)

        parts = re.split(r"[-_]", text)

        if parts:
            return parts[0]

        return None

    # ---------------------------------------------------------
    # DOMAIN NORMALIZATION
    # ---------------------------------------------------------

    def _normalize_domain(self, domain, df):

        if df.empty:
            return df

        result = df.copy()

        # Clean strings
        for column in result.columns:

            if (
                result[column].dtype == "object"
                and column not in [
                    "LBORRES",
                    "VSORRES",
                    "EGORRES",
                ]
            ):
                result[column] = result[column].apply(
                    clean_string
                )

        # Normalize dates
        for column in DATE_COLUMNS.get(domain, []):

            if column in result.columns:

                result[f"{column}_DT"] = result[
                    column
                ].apply(parse_date)

        # Normalize labs
        if domain == "LB":

            normalized_rows = []

            for _, row in result.iterrows():

                normalized_rows.append(
                    self._normalize_lab_row(row)
                )

            result = pd.DataFrame(
                normalized_rows
            )

        return result.reset_index(drop=True)

    # ---------------------------------------------------------
    # BUILD STUDY GRAPH
    # ---------------------------------------------------------

    def build(self, cut=None):

        if cut is None:
            cut = self._latest_cut()

        cut = int(cut)

        self.current_cut = cut
        self.protocol_version = (
            self._protocol_for_cut(cut)
        )

        self.data = {}

        self.nodes = {}
        self.edges = []

        self.subject_index = {}
        self.record_index = {}

        # -----------------------------------------------------
        # PROCESS EACH DOMAIN
        # -----------------------------------------------------

        for domain in DOMAIN_FILES:

            if domain not in self.raw:
                continue

            df = self.raw[domain].copy()

            # Filter according to cut
            df = self._filter_to_cut(
                df,
                cut
            )

            # Apply corrections
            df = self._apply_corrections(
                domain,
                df,
                cut
            )

            # Normalize
            df = self._normalize_domain(
                domain,
                df
            )

            # Keep valid USUBJID
            if "USUBJID" in df.columns:

                df = df[
                    df["USUBJID"].notna()
                ]

                df = df[
                    df["USUBJID"].astype(str).str.strip()
                    != ""
                ]

            self.data[domain] = (
                df.reset_index(drop=True)
            )

        # -----------------------------------------------------
        # CREATE SUBJECT NODES FROM DM
        # -----------------------------------------------------

        dm = self.data.get(
            "DM",
            pd.DataFrame()
        )

        if not dm.empty:

            for _, row in dm.iterrows():

                usubjid = clean_string(
                    row.get("USUBJID")
                )

                if not usubjid:
                    continue

                node_id = f"SUBJECT:{usubjid}"

                subject = row.to_dict()

                subject["USUBJID"] = usubjid

                if not subject.get("SITEID"):
                    subject["SITEID"] = (
                        self._site_from_usubjid(
                            usubjid
                        )
                    )

                self.nodes[node_id] = {
                    "type": "subject",
                    "id": node_id,
                    "domain": "DM",
                    "USUBJID": usubjid,
                    "data": subject,
                }

                self.subject_index[
                    usubjid
                ] = node_id

        # -----------------------------------------------------
        # CREATE RECORD NODES
        # -----------------------------------------------------

        for domain, df in self.data.items():

            if df.empty:
                continue

            seq_column = (
                SEQUENCE_COLUMNS.get(domain)
            )

            for row_position, row in df.iterrows():

                usubjid = clean_string(
                    row.get("USUBJID")
                )

                if not usubjid:
                    continue

                seq = None

                if seq_column is not None:
                    seq = clean_string(
                        row.get(seq_column)
                    )

                # Record identity:
                # domain + USUBJID + sequence
                if seq is not None:

                    record_id = (
                        f"{domain}:"
                        f"{usubjid}:"
                        f"{seq}"
                    )

                else:

                    record_id = (
                        f"{domain}:"
                        f"{usubjid}:"
                        f"{row_position + 1}"
                    )

                record = row.to_dict()

                record["domain"] = domain
                record["USUBJID"] = usubjid
                record["record_id"] = record_id

                node_id = f"RECORD:{record_id}"

                self.nodes[node_id] = {
                    "type": "record",
                    "id": node_id,
                    "domain": domain,
                    "USUBJID": usubjid,
                    "seq": seq,
                    "data": record,
                }

                self.record_index[
                    record_id
                ] = node_id

                # Add subject → record edge
                if usubjid in self.subject_index:

                    self.edges.append(
                        {
                            "source":
                                self.subject_index[
                                    usubjid
                                ],
                            "target":
                                node_id,
                            "type":
                                "HAS_RECORD",
                        }
                    )

        return self

    # ---------------------------------------------------------
    # PATIENT 360
    # ---------------------------------------------------------

    def patient360(self, usubjid):

        usubjid = clean_string(usubjid)

        if not usubjid:
            return {
                "USUBJID": None,
                "subject": None,
                "records": [],
            }

        subject_node = self.subject_index.get(
            usubjid
        )

        subject_data = None

        if subject_node:

            subject_data = self.nodes[
                subject_node
            ]["data"]

        records = []

        for domain, df in self.data.items():

            if df.empty:
                continue

            if "USUBJID" not in df.columns:
                continue

            subject_records = df[
                df["USUBJID"].astype(str)
                == str(usubjid)
            ]

            for _, row in subject_records.iterrows():

                record = row.to_dict()

                record["domain"] = domain

                records.append(record)

        return {
            "USUBJID": usubjid,
            "subject": subject_data,
            "records": records,
        }

    # ---------------------------------------------------------
    # SUBJECT LIST
    # ---------------------------------------------------------

    def get_subjects(self):

        subjects = []

        for usubjid, node_id in (
            self.subject_index.items()
        ):

            subjects.append(
                self.nodes[node_id]
            )

        return subjects

    # ---------------------------------------------------------
    # RECORD LIST
    # ---------------------------------------------------------

    def get_records(
        self,
        usubjid=None,
        domain=None
    ):

        records = []

        for node in self.nodes.values():

            if node["type"] != "record":
                continue

            if (
                usubjid is not None
                and node["USUBJID"]
                != usubjid
            ):
                continue

            if (
                domain is not None
                and node["domain"]
                != domain
            ):
                continue

            records.append(node)

        return records

    # ---------------------------------------------------------
    # GET ONE RECORD
    # ---------------------------------------------------------

    def get_record(
        self,
        domain,
        usubjid,
        seq
    ):

        record_id = (
            f"{domain}:"
            f"{usubjid}:"
            f"{seq}"
        )

        node_id = self.record_index.get(
            record_id
        )

        if node_id is None:
            return None

        return self.nodes[node_id]

    # ---------------------------------------------------------
    # SUBJECTS AT SITE
    # ---------------------------------------------------------

    def get_subjects_at_site(
        self,
        site_id
    ):

        site_id = str(site_id)

        result = []

        for node in self.get_subjects():

            data = node.get(
                "data",
                {}
            )

            subject_site = data.get(
                "SITEID"
            )

            if (
                subject_site is not None
                and str(subject_site)
                == site_id
            ):
                result.append(node)

        return result

    # ---------------------------------------------------------
    # RECORD EXISTS
    # ---------------------------------------------------------

    def record_exists(
        self,
        domain,
        usubjid,
        seq
    ):

        record_id = (
            f"{domain}:"
            f"{usubjid}:"
            f"{seq}"
        )

        return (
            record_id
            in self.record_index
        )

    # ---------------------------------------------------------
    # RECORD REFERENCE FOR EVIDENCE
    # ---------------------------------------------------------

    def record_ref(
        self,
        domain,
        usubjid,
        seq
    ):

        record = self.get_record(
            domain,
            usubjid,
            seq
        )

        if record is None:
            return None

        return {
            "domain": domain,
            "USUBJID": usubjid,
            "seq": seq,
            "record_id": record[
                "data"
            ].get(
                "record_id"
            ),
        }

    # ---------------------------------------------------------
    # GRAPH STATISTICS
    # ---------------------------------------------------------

    def stats(self):

        return {
            "subjects": len(
                self.subject_index
            ),
            "records": len(
                self.record_index
            ),
            "nodes": len(
                self.nodes
            ),
            "edges": len(
                self.edges
            ),
            "cut": self.current_cut,
            "protocol_version":
                self.protocol_version,
        }

    # ---------------------------------------------------------
    # SAVE GRAPH STATS
    # ---------------------------------------------------------

    def save_graph_stats(
        self,
        output_file="graph_stats.json"
    ):

        stats = self.stats()

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                stats,
                file,
                indent=2
            )

        return stats


# =============================================================
# TEST / COMMAND LINE
# =============================================================

if __name__ == "__main__":

    data_folder = Path("data")

    print("=" * 60)
    print("ATLAS - StudyGraph")
    print("=" * 60)

    if not data_folder.exists():

        print(
            "ERROR: 'data' folder was not found."
        )

        print(
            "Create a data folder and place the CSV files inside it."
        )

        raise SystemExit(1)

    try:

        graph = StudyGraph(
            data_folder
        )

        print("\nLoaded domains:")

        for domain in graph.raw:

            rows = len(
                graph.raw[domain]
            )

            print(
                f"  {domain}: {rows} rows"
            )

        graph.build()

        print("\nGraph statistics:")

        print(
            json.dumps(
                graph.stats(),
                indent=2
            )
        )

        graph.save_graph_stats()

        print(
            "\nGraph statistics saved to:"
            " graph_stats.json"
        )

        subjects = graph.get_subjects()

        if subjects:

            first_subject = subjects[0][
                "USUBJID"
            ]

            print(
                f"\nTesting patient360(): "
                f"{first_subject}"
            )

            patient = graph.patient360(
                first_subject
            )

            print(
                "Number of records:",
                len(
                    patient["records"]
                )
            )

        else:

            print(
                "\nNo subjects found."
            )

    except Exception as error:

        print(
            "\nERROR:"
        )

        print(error)
        raise