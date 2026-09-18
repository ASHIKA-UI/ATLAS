from ashika_study_graph import StudyGraph

DATA_FOLDER = "data"

print("=" * 60)
print("ATLAS - Edge Case Test")
print("=" * 60)

graph = StudyGraph(DATA_FOLDER)
graph.build(cut=12)

# Test 1: Unknown subject
print("\n1. Unknown subject test")

try:
    result = graph.patient360("UNKNOWN-SUBJECT-999")
    print("Result:", result)
    print("PASS - No crash")
except Exception as e:
    print("FAIL - Error:", e)


# Test 2: Existing subject
print("\n2. Existing subject test")

try:
    result = graph.patient360("042-S01-001")
    print("Subject:", result["USUBJID"])
    print("Records:", len(result["records"]))
    print("PASS - Existing subject retrieved")
except Exception as e:
    print("FAIL - Error:", e)


# Test 3: Empty/invalid subject values
print("\n3. Empty subject test")

for subject_id in ["", None, "12345"]:
    try:
        result = graph.patient360(subject_id)
        print("Input:", repr(subject_id))
        print("Result:", result)
        print("PASS - No crash")
    except Exception as e:
        print("Input:", repr(subject_id))
        print("FAIL - Error:", e)

print("\n" + "=" * 60)
print("Edge case test completed.")
print("=" * 60)