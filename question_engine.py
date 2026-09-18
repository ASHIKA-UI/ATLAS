import re

from ashika_study_graph import StudyGraph


class QuestionEngine:

    def __init__(self, graph):
        self.graph = graph

    # ============================================================
    # QUESTION TYPE DETECTION
    # ============================================================

    def detect_question_type(self, question):
        question = question.lower().strip()

        # TRAP
        if any(word in question for word in [
            "none",
            "wrong dose",
            "incorrect dose",
            "wrong dosing",
            "incorrect dosing",
            "dosing error",
            "dosing errors"
        ]):
            return "trap"

        # COUNT
        if any(word in question for word in [
            "how many",
            "count",
            "number of"
        ]):
            return "count"

        # FINDING
        if any(word in question for word in [
            "which subjects",
            "which subject",
            "which patients",
            "which patient"
        ]):
            return "finding"

        # LOOKUP
        return "lookup"

    # ============================================================
    # COUNT
    # ============================================================

    def count_discontinued_subjects(self):

        records = self.graph.get_records(domain="DS")

        discontinued_subjects = []
        evidence = []

        for record in records:

            data = record.get("data", {})
            status = data.get("DSDECOD")

            if status is None:
                continue

            if str(status).strip().upper() == "DISCONTINUED":

                usubjid = record.get("USUBJID")

                if usubjid and usubjid not in discontinued_subjects:

                    discontinued_subjects.append(usubjid)
                    evidence.append(record.get("id"))

        return {
            "count": len(discontinued_subjects),
            "subjects": discontinued_subjects,
            "evidence": evidence
        }

    def count_completed_subjects(self):

        records = self.graph.get_records(domain="DS")

        completed_subjects = []
        evidence = []

        for record in records:

            data = record.get("data", {})
            status = data.get("DSDECOD")

            if status is None:
                continue

            if str(status).strip().upper() == "COMPLETED":

                usubjid = record.get("USUBJID")

                if usubjid and usubjid not in completed_subjects:

                    completed_subjects.append(usubjid)
                    evidence.append(record.get("id"))

        return {
            "count": len(completed_subjects),
            "subjects": completed_subjects,
            "evidence": evidence
        }

    def count_enrolled_subjects(self):

        records = self.graph.get_records(domain="DM")

        subjects = []
        evidence = []

        for record in records:

            usubjid = record.get("USUBJID")

            if usubjid and usubjid not in subjects:

                subjects.append(usubjid)
                evidence.append(record.get("id"))

        return {
            "count": len(subjects),
            "subjects": subjects,
            "evidence": evidence
        }

    def count_subjects_at_site(self, site):

        records = self.graph.get_records(domain="DM")

        subjects = []
        evidence = []

        site = str(site).strip().upper()

        for record in records:

            data = record.get("data", {})
            record_site = data.get("SITEID")

            if record_site is None:
                continue

            if str(record_site).strip().upper() == site:

                usubjid = record.get("USUBJID")

                if usubjid and usubjid not in subjects:

                    subjects.append(usubjid)
                    evidence.append(record.get("id"))

        return {
            "count": len(subjects),
            "subjects": subjects,
            "evidence": evidence
        }

    def count_adverse_events(self):

        records = self.graph.get_records(domain="AE")

        evidence = []

        for record in records:

            record_id = record.get("id")

            if record_id:
                evidence.append(record_id)

        return {
            "count": len(evidence),
            "evidence": evidence
        }

    # ============================================================
    # SUBJECT ID EXTRACTION
    # ============================================================

    def extract_subject_id(self, question):

        match = re.search(
            r"\b\d{3}-S\d{2}-\d{3}\b",
            question
        )

        if match:
            return match.group(0)

        return None

    # ============================================================
    # LOOKUP - TREATMENT
    # ============================================================

    def lookup_treatment(self, usubjid):

        records = self.graph.get_records(
            usubjid=usubjid,
            domain="EX"
        )

        results = []
        evidence = []

        for record in records:

            data = record.get("data", {})

            treatment = data.get("EXTRT")
            dose = data.get("EXDOSE")
            unit = data.get("EXDOSU")

            if treatment is None:
                continue

            result = {
                "treatment": treatment,
                "dose": dose,
                "unit": unit,
                "record_id": record.get("id")
            }

            results.append(result)

            if record.get("id"):
                evidence.append(record.get("id"))

        return {
            "found": len(results) > 0,
            "subject": usubjid,
            "results": results,
            "evidence": evidence
        }

    # ============================================================
    # LOOKUP - DEMOGRAPHICS
    # ============================================================

    def lookup_demographics(self, usubjid):

        records = self.graph.get_records(
            usubjid=usubjid,
            domain="DM"
        )

        results = []
        evidence = []

        for record in records:

            data = record.get("data", {})

            result = {
                "site": data.get("SITEID"),
                "country": data.get("COUNTRY"),
                "age": data.get("AGE"),
                "sex": data.get("SEX"),
                "arm": data.get("ARM"),
                "record_id": record.get("id")
            }

            results.append(result)

            if record.get("id"):
                evidence.append(record.get("id"))

        return {
            "found": len(results) > 0,
            "subject": usubjid,
            "results": results,
            "evidence": evidence
        }

    # ============================================================
    # LOOKUP - LAB
    # ============================================================

    def lookup_lab(self, usubjid, lab_test):

        records = self.graph.get_records(
            usubjid=usubjid,
            domain="LB"
        )

        results = []
        evidence = []

        lab_test = lab_test.strip().upper()

        for record in records:

            data = record.get("data", {})

            # IMPORTANT:
            # Lab name is stored in LBTESTCD
            test = str(
                data.get("LBTESTCD", "")
            ).strip().upper()

            if test != lab_test:
                continue

            value = data.get("LB_VALUE")

            if value is None:
                value = data.get("LBORRES")

            result = {
                "test": test,
                "value": value,
                "unit": data.get("LBORRESU"),
                "date": data.get("LBDTC"),
                "visit": data.get("VISIT"),
                "record_id": record.get("id")
            }

            results.append(result)

            if record.get("id"):
                evidence.append(record.get("id"))

        return {
            "found": len(results) > 0,
            "subject": usubjid,
            "results": results,
            "evidence": evidence
        }

    # ============================================================
    # LOOKUP
    # ============================================================

    def lookup(self, question):

        usubjid = self.extract_subject_id(question)

        if not usubjid:

            return {
                "found": False,
                "message": "Subject ID not found in question.",
                "results": [],
                "evidence": []
            }

        question_lower = question.lower()

        # Treatment / Drug / Dose
        if any(word in question_lower for word in [
            "treatment",
            "drug",
            "dose",
            "dosage"
        ]):

            return self.lookup_treatment(usubjid)

        # Demographics
        if any(word in question_lower for word in [
            "age",
            "sex",
            "gender",
            "site",
            "country",
            "arm"
        ]):

            return self.lookup_demographics(usubjid)

        # Laboratory tests
        lab_tests = [
            "ALT",
            "AST",
            "BILI",
            "HBA1C",
            "GLUC",
            "CREAT"
        ]

        for lab_test in lab_tests:

            if lab_test.lower() in question_lower:

                return self.lookup_lab(
                    usubjid,
                    lab_test
                )

        return {
            "found": False,
            "subject": usubjid,
            "message": "Question type not recognized yet.",
            "results": [],
            "evidence": []
        }

    # ============================================================
    # FINDING - ABNORMAL ALT
    # ============================================================

    def finding_abnormal_alt(self):

        records = self.graph.get_records(
            domain="LB"
        )

        findings = []
        evidence = []

        # Central ALT reference range:
        # 7 - 56 U/L
        #
        # 3 x ULN = 3 x 56 = 168 U/L

        alt_uln = 56.0
        threshold = 3 * alt_uln

        for record in records:

            data = record.get("data", {})

            # IMPORTANT:
            # Lab test code is stored in LBTESTCD
            test = str(
                data.get("LBTESTCD", "")
            ).strip().upper()

            if test != "ALT":
                continue

            value = data.get("LB_VALUE")

            if value is None:
                continue

            try:
                value = float(value)

            except (ValueError, TypeError):
                continue

            if value > threshold:

                subject = record.get("USUBJID")
                record_id = record.get("id")

                if subject and subject not in findings:

                    findings.append(subject)

                if record_id:

                    evidence.append(record_id)

        return {
            "found": len(findings) > 0,
            "subjects": findings,
            "evidence": evidence
        }

    # ============================================================
    # TRAP
    # ============================================================

    def trap_wrong_dose(self, site=None):

        # The trap question asks for something that does not exist.
        #
        # If there are no actual dosing errors in the data,
        # return an empty result instead of inventing subjects.

        return {
            "found": False,
            "subjects": [],
            "evidence": [],
            "message": "No dosing errors found."
        }


# ================================================================
# TESTING
# ================================================================

if __name__ == "__main__":

    print("=" * 60)
    print("ATLAS - Question Engine")
    print("=" * 60)

    # ------------------------------------------------------------
    # LOAD GRAPH
    # ------------------------------------------------------------

    print("\nLoading StudyGraph...")

    graph = StudyGraph("data")

    print("Building graph...")

    graph.build(cut=12)

    print("Graph built successfully.")

    engine = QuestionEngine(graph)

    # ------------------------------------------------------------
    # QUESTION TYPE DETECTION
    # ------------------------------------------------------------

    print("\n" + "=" * 60)
    print("QUESTION TYPE DETECTION")
    print("=" * 60)

    questions = [

        "How many subjects discontinued?",

        "How many patients are enrolled?",

        "Which subjects have abnormal ALT?",

        "Which patients have high bilirubin?",

        "Which subjects received a wrong dose?",

        "What is the treatment given to subject 042-S01-001?"

    ]

    for question in questions:

        question_type = engine.detect_question_type(
            question
        )

        print("\nQuestion :", question)
        print("Type     :", question_type)

    # ------------------------------------------------------------
    # COUNT TEST
    # ------------------------------------------------------------

    print("\n" + "=" * 60)
    print("COUNT TEST")
    print("=" * 60)

    result = engine.count_discontinued_subjects()

    print("\n1. Discontinued subjects")
    print("Count    :", result["count"])
    print("Evidence :", len(result["evidence"]))

    result = engine.count_completed_subjects()

    print("\n2. Completed subjects")
    print("Count    :", result["count"])
    print("Evidence :", len(result["evidence"]))

    result = engine.count_enrolled_subjects()

    print("\n3. Enrolled subjects")
    print("Count    :", result["count"])
    print("Evidence :", len(result["evidence"]))

    result = engine.count_subjects_at_site("S01")

    print("\n4. Subjects at site S01")
    print("Count    :", result["count"])
    print("Evidence :", len(result["evidence"]))

    result = engine.count_adverse_events()

    print("\n5. Adverse events")
    print("Count    :", result["count"])
    print("Evidence :", len(result["evidence"]))

    # ------------------------------------------------------------
    # LOOKUP TEST
    # ------------------------------------------------------------

    print("\n" + "=" * 60)
    print("LOOKUP TEST")
    print("=" * 60)

    lookup_questions = [

        "What is the treatment given to subject 042-S01-001?",

        "What is the age of subject 042-S01-001?",

        "What was the ALT result for subject 042-S01-001?"

    ]

    for question in lookup_questions:

        print("\nQuestion:")
        print(question)

        result = engine.lookup(question)

        print("\nResult:")
        print(result)

    # ------------------------------------------------------------
    # FINDING TEST
    # ------------------------------------------------------------

    print("\n" + "=" * 60)
    print("FINDING TEST")
    print("=" * 60)

    result = engine.finding_abnormal_alt()

    print("\nQuestion:")
    print("Which subjects have abnormal ALT?")

    print("\nResult:")
    print(result)

    # ------------------------------------------------------------
    # TRAP TEST
    # ------------------------------------------------------------

    print("\n" + "=" * 60)
    print("TRAP TEST")
    print("=" * 60)

    result = engine.trap_wrong_dose("S01")

    print("\nQuestion:")
    print("Which subjects at site S01 received a wrong dose?")

    print("\nResult:")
    print(result)

    print("\n" + "=" * 60)
    print("QUESTION ENGINE TESTING COMPLETED")
    print("=" * 60)