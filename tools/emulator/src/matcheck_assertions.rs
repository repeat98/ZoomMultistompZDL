// Kept independent of Ziddle so the verdict logic can be regression-tested locally.
pub fn mismatches(actual: &[Result<f32, String>], expected: &[f32]) -> Vec<String> {
    let mut errors = Vec::new();
    if actual.len() != expected.len() {
        errors.push(format!("length: got {}, expected {}", actual.len(), expected.len()));
    }
    for (i, (got, want)) in actual.iter().zip(expected).enumerate() {
        let slot = if i == 0 { 0 } else { i + 4 };
        match got {
            Ok(value) if value.is_finite() && (*value - *want).abs() <= 0.00001 => {},
            _ => errors.push(format!("params[{slot}]: got {got:?}, expected {want}")),
        }
    }
    errors
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_only_expected_values() {
        assert!(mismatches(&[Ok(1.0), Ok(0.11)], &[1.0, 0.11]).is_empty());
        for bad in [0.0, 11.0, 0.22, f32::NAN, f32::INFINITY] {
            assert!(!mismatches(&[Ok(1.0), Ok(bad)], &[1.0, 0.11]).is_empty());
        }
    }
    #[test]
    fn checks_bypass_and_ninth_knob() {
        let expected = vec![1.0; 10];
        for slot in [0, 9] {
            let mut actual = vec![Ok(1.0); 10];
            actual[slot] = Ok(0.0);
            assert_eq!(mismatches(&actual, &expected).len(), 1);
        }
    }
    #[test]
    fn rejects_missing_and_unreadable_values() {
        assert!(!mismatches(&[], &[1.0]).is_empty());
        assert!(!mismatches(&[Err("unmapped".into())], &[1.0]).is_empty());
    }
}
