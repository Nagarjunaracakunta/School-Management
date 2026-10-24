import { useState } from 'react';

// Small form helper: tracks values, submit state and the API error for one form.
export function useForm(initial, onSubmit) {
  const [values, setValues] = useState(initial);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const bind = (name) => ({
    name,
    value: values[name],
    onChange: (e) => setValues((v) => ({ ...v, [name]: e.target.value })),
  });

  const submit = async (e) => {
    e.preventDefault();
    if (submitting) return; // guards against double-click
    setSubmitting(true);
    setError(null);
    setDone(null);
    try {
      const result = await onSubmit(values);
      setDone(result ?? true);
      setValues(initial);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return { values, bind, submit, submitting, error, done };
}
