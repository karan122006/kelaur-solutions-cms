"""Allergy cross-check used by 3.0 (prescribing) and 4.0 (dispensing).
A recorded allergy matches a medicine by name or by drug class (e.g. Penicillin -> Amoxicillin)."""
CLASSES = {
    "penicillin": ["penicillin", "amoxicillin", "ampicillin", "cloxacillin"],
    "nsaid": ["ibuprofen", "diclofenac", "mefenamic", "naproxen", "aspirin"],
    "ibuprofen": ["ibuprofen", "diclofenac", "mefenamic", "naproxen"],
    "sulfa": ["sulfamethoxazole", "co-trimoxazole"],
    "paracetamol": ["paracetamol"],
}


def allergy_conflicts(allergies, med_names):
    text = (allergies or "").lower()
    if not text.strip() or text.strip() in ("none known", "none"):
        return []
    words = [w.strip() for w in text.replace(";", ",").split(",") if w.strip()]
    hits = []
    for name in med_names:
        n = name.lower()
        for w in words:
            keys = CLASSES.get(w.split()[0], [w])
            if any(k in n for k in keys) or w in n:
                hits.append(name)
                break
    return hits
