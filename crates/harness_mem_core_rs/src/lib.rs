use std::collections::BTreeMap;

pub const API_VERSION: &str = "v4.0.2";

pub fn api_version() -> &'static str {
    API_VERSION
}

pub fn reciprocal_rank_fusion(lists: &[Vec<String>], k: f64) -> BTreeMap<String, f64> {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rrf_is_deterministic() {
        let lists = vec![
            vec!["a".to_string(), "b".to_string()],
            vec!["b".to_string(), "a".to_string()],
        ];
        let scores = reciprocal_rank_fusion(&lists, 60.0);
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
}
