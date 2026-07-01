use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use serde_json::{json, Map, Number, Value};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet, HashMap};

pub const API_VERSION: &str = "v4.0.2";

pub fn api_version() -> &'static str {
    API_VERSION
}

pub fn reciprocal_rank_fusion_scores(lists: &[Vec<String>], k: f64) -> BTreeMap<String, f64> {
    let mut scores: BTreeMap<String, f64> = BTreeMap::new();
    for ranked in lists {
        for (idx, item) in ranked.iter().enumerate() {
            if item.is_empty() {
                continue;
            }
            let score = 1.0 / (k + idx as f64 + 1.0);
            *scores.entry(item.clone()).or_insert(0.0) += score;
        }
    }
    scores
}

pub fn tokens(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        if ch.is_ascii_alphanumeric() || ch == '_' {
            current.push(ch.to_ascii_lowercase());
            continue;
        }
        push_unique(&mut out, &mut current);
    }
    push_unique(&mut out, &mut current);
    out
}

fn push_unique(out: &mut Vec<String>, current: &mut String) {
    if current.is_empty() {
        return;
    }
    if !out.iter().any(|item| item == current) {
        out.push(current.clone());
    }
    current.clear();
}

#[pyfunction(name = "api_version")]
fn py_api_version() -> &'static str {
    API_VERSION
}

#[pyfunction(name = "scan_jsonl")]
fn py_scan_jsonl(text: &str) -> PyResult<String> {
    let mut records: Vec<Map<String, Value>> = Vec::new();
    let mut errors: Vec<Value> = Vec::new();

    for (idx, line) in text.lines().enumerate() {
        let stripped = line.trim();
        if stripped.is_empty() {
            continue;
        }
        match serde_json::from_str::<Value>(stripped) {
            Ok(Value::Object(record)) => records.push(record),
            Ok(_) => errors.push(json!({
                "line": idx + 1,
                "code": "HM-411",
                "message": "JSONL record must be an object",
            })),
            Err(err) => errors.push(json!({
                "line": idx + 1,
                "code": "HM-410",
                "message": err.to_string(),
            })),
        }
    }

    serde_json::to_string(&json!({
        "records": records,
        "errors": errors,
    }))
    .map_err(|err| PyValueError::new_err(err.to_string()))
}

#[pyfunction(name = "reciprocal_rank_fusion")]
fn py_reciprocal_rank_fusion(lists_json: &str, k: f64) -> PyResult<String> {
    let lists: Vec<Vec<String>> = serde_json::from_str(lists_json)
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
    let scores = reciprocal_rank_fusion_scores(&lists, k);
    let ordered = ordered_score_pairs(scores);
    serde_json::to_string(&ordered).map_err(|err| PyValueError::new_err(err.to_string()))
}

#[pyfunction]
fn build_bulk_index_rows(payloads_json: &str) -> PyResult<String> {
    let payloads: Vec<Value> = serde_json::from_str(payloads_json)
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
    let rows: Vec<Value> = payloads
        .iter()
        .map(build_bulk_index_row)
        .collect();
    serde_json::to_string(&rows).map_err(|err| PyValueError::new_err(err.to_string()))
}

#[pyfunction]
fn rank_candidates(
    rows_json: &str,
    query: &str,
    source_diversity_penalty: f64,
) -> PyResult<String> {
    let rows: Vec<Value> = serde_json::from_str(rows_json)
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
    let query_tokens: BTreeSet<String> = tokens(query).into_iter().collect();
    let mut source_seen: HashMap<String, usize> = HashMap::new();
    let mut ranked: Vec<Value> = Vec::new();

    for row in rows {
        let mut row_object = match row {
            Value::Object(map) => map,
            _ => continue,
        };
        let row_id = row_object
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let token_set: BTreeSet<String> = row_object
            .get("tokens")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(ToOwned::to_owned)
                    .collect()
            })
            .unwrap_or_default();
        let exact_overlap = query_tokens.intersection(&token_set).count() as f64;
        let confidence = value_as_f64(row_object.get("confidence")).unwrap_or(0.0);
        let source_id = row_object
            .get("source_id")
            .and_then(Value::as_str)
            .or_else(|| row_object.get("project_id").and_then(Value::as_str))
            .unwrap_or("")
            .to_string();
        let diversity_seen = source_seen.get(&source_id).copied().unwrap_or(0);
        source_seen.insert(source_id, diversity_seen + 1);
        let truth_status = row_object
            .get("truth_status")
            .and_then(Value::as_str);
        let metadata_penalty = if matches!(
            truth_status,
            None
                | Some("auto_confirmed")
                | Some("user_confirmed")
                | Some("confirmed_current")
        ) {
            0.0
        } else {
            0.2
        };
        let score = exact_overlap + confidence - metadata_penalty
            - (diversity_seen as f64 * source_diversity_penalty);
        row_object.insert("id".to_string(), Value::String(row_id));
        row_object.insert(
            "score".to_string(),
            json_number(round_six(score)),
        );
        ranked.push(Value::Object(row_object));
    }

    ranked.sort_by(|left, right| {
        let left_score = left
            .get("score")
            .and_then(|value| value_as_f64(Some(value)))
            .unwrap_or(0.0);
        let right_score = right
            .get("score")
            .and_then(|value| value_as_f64(Some(value)))
            .unwrap_or(0.0);
        right_score
            .partial_cmp(&left_score)
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                left.get("id")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .cmp(right.get("id").and_then(Value::as_str).unwrap_or(""))
            })
    });

    serde_json::to_string(&ranked).map_err(|err| PyValueError::new_err(err.to_string()))
}

#[pyfunction(name = "tokens")]
fn py_tokens(text: &str) -> Vec<String> {
    tokens(text)
}

#[pymodule]
fn harness_mem_core_rs(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(py_api_version, module)?)?;
    module.add_function(wrap_pyfunction!(py_scan_jsonl, module)?)?;
    module.add_function(wrap_pyfunction!(py_reciprocal_rank_fusion, module)?)?;
    module.add_function(wrap_pyfunction!(build_bulk_index_rows, module)?)?;
    module.add_function(wrap_pyfunction!(rank_candidates, module)?)?;
    module.add_function(wrap_pyfunction!(py_tokens, module)?)?;
    Ok(())
}

fn ordered_score_pairs(scores: BTreeMap<String, f64>) -> Vec<(String, f64)> {
    let mut ordered: Vec<(String, f64)> = scores.into_iter().collect();
    ordered.sort_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(Ordering::Equal)
            .then_with(|| left.0.cmp(&right.0))
    });
    ordered
}

fn build_bulk_index_row(payload: &Value) -> Value {
    let entity_id = payload
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let text = search_text(payload);
    let token_list = tokens(&text);
    let exact_terms: Vec<String> = token_list
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let truth_status = payload
        .get("status")
        .cloned()
        .unwrap_or_else(|| Value::String("pending".to_string()));
    let confidence = payload.get("confidence").cloned().unwrap_or(Value::Null);
    json!({
        "id": entity_id,
        "tokens": token_list,
        "exact_terms": exact_terms,
        "trigrams": trigrams(&text),
        "metadata": {
            "project_id": project_id(payload),
            "truth_status": truth_status,
            "confidence": confidence,
        }
    })
}

fn search_text(payload: &Value) -> String {
    let mut parts: Vec<String> = Vec::new();
    for key in [
        "raw_content",
        "content",
        "pattern",
        "trigger",
        "evidence",
        "summary",
        "activation_condition",
    ] {
        if let Some(value) = payload.get(key).and_then(Value::as_str) {
            parts.push(value.to_string());
        }
    }
    if let Some(steps) = payload.get("steps").and_then(Value::as_array) {
        for item in steps {
            if let Some(value) = item.as_str() {
                parts.push(value.to_string());
            } else {
                parts.push(item.to_string());
            }
        }
    }
    parts.join("\n")
}

fn project_id(payload: &Value) -> Value {
    if let Some(value) = payload.get("project_name").cloned() {
        return value;
    }
    payload
        .get("metadata")
        .and_then(Value::as_object)
        .and_then(|metadata| metadata.get("project_name").cloned())
        .unwrap_or(Value::Null)
}

fn trigrams(text: &str) -> Vec<String> {
    let normalized = text
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase();
    if normalized.is_empty() {
        return Vec::new();
    }
    let chars: Vec<char> = normalized.chars().collect();
    if chars.len() < 3 {
        return vec![normalized];
    }
    let mut set: BTreeSet<String> = BTreeSet::new();
    for index in 0..=(chars.len() - 3) {
        let gram: String = chars[index..index + 3].iter().collect();
        set.insert(gram);
    }
    set.into_iter().collect()
}

fn json_number(value: f64) -> Value {
    Value::Number(Number::from_f64(value).unwrap_or_else(|| Number::from(0)))
}

fn round_six(value: f64) -> f64 {
    (value * 1_000_000.0).round() / 1_000_000.0
}

fn value_as_f64(value: Option<&Value>) -> Option<f64> {
    value.and_then(|item| match item {
        Value::Number(number) => number.as_f64(),
        Value::String(text) => text.parse::<f64>().ok(),
        _ => None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rrf_is_deterministic() {
        let lists = vec![
            vec!["a".to_string(), "b".to_string()],
            vec!["b".to_string(), "a".to_string()],
        ];
        let scores = reciprocal_rank_fusion_scores(&lists, 60.0);
        assert_eq!(scores.len(), 2);
        assert!(scores["a"] > 0.0);
        assert!(scores["b"] > 0.0);
    }

    #[test]
    fn tokenizer_dedupes_in_order() {
        assert_eq!(
            tokens("Storage v2, storage_v2; RRF!"),
            vec![
                "storage".to_string(),
                "v2".to_string(),
                "storage_v2".to_string(),
                "rrf".to_string(),
            ]
        );
    }

    #[test]
    fn scan_jsonl_keeps_records_and_errors() {
        let payload = py_scan_jsonl("{\"id\":\"ok\"}\nnot-json\n[1,2]\n").unwrap();
        let value: Value = serde_json::from_str(&payload).unwrap();
        assert_eq!(value["records"].as_array().unwrap().len(), 1);
        assert_eq!(value["errors"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn rank_candidates_orders_by_score_then_id() {
        let rows = json!([
            {
                "id": "a",
                "tokens": ["storage", "v2"],
                "confidence": 0.8,
                "truth_status": "user_confirmed",
                "project_id": "demo"
            },
            {
                "id": "b",
                "tokens": ["storage"],
                "confidence": 0.8,
                "truth_status": "pending",
                "project_id": "demo"
            }
        ]);
        let ranked = rank_candidates(&rows.to_string(), "storage v2", 0.05).unwrap();
        let value: Value = serde_json::from_str(&ranked).unwrap();
        assert_eq!(value[0]["id"], "a");
        assert_eq!(value[1]["id"], "b");
    }
}
