# Coda di transizioni dei registri

Ogni corsia che deve toccare un registro NON lo scrive a mano: deposita qui una richiesta e la
lascia applicare. L'applicatore calcola l'indentazione dall'ancora, e' idempotente per campo, e
ripristina il file se dopo l'edit non e' piu' valido.

```
python3 registers/apply_transitions.py --workspace <progetto> --dir <progetto>/pending-transitions
```

## Formato

`<timestamp>-<corsia>.yaml`, applicate in ordine di nome:

```yaml
schema: project-console-transition/1.0
requested_by: /corsia
requested_at: '2026-01-01T09:00:00+02:00'
file: state.yaml
anchor: "- task_id: ES01A"
field: status
text: taken
```

L'ancora e' la riga di APERTURA della voce, riprodotta esattamente, e deve essere unica. Campi
facoltativi: `occurrence` (la n-esima voce con la stessa ancora), `item` (una voce NUOVA al posto
di `field`+`text`), `position: before|after`, `mapping` (per i campi che sono mappe).
