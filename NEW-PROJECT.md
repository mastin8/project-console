# Nuovo progetto — punto di partenza

Ogni progetto, anche un foglio bianco, parte da questa repository.

Se Git, Python e Codex CLI sono già installati, il percorso rapido è il prompt parametrico in
[`BOOTSTRAP-PROMPT.md`](BOOTSTRAP-PROMPT.md).

1. Scarica/clona `project-console`.
2. Crea il workspace:

   ```bash
   python3 scaffold.py /percorso/progetto --project "Nome del progetto"
   ```

3. Apri `FIRST-PROMPT.md`. Nella parte **Prompt dell'utente** scrivi cosa vuoi ottenere, senza
   tradurlo in task tecnici.
4. Consegna all'agente il primo prompt con il suo **Addendum obbligatorio**. L'agente non deve
   iniziare a scrivere codice: deve intervistarti e compilare `constitution.md`.
5. Controlla la constitution: obiettivo, fuori perimetro, stack, deliverable, numero e ampiezza dei
   task, skill, flusso normale/rigoroso, parallelismo, test, accettazione, rischi e stop rule.
6. Avvia il console, apri **Costituzione**, correggi se serve e premi **Approva e blocca**. Questo
   è l'unico punto in cui la Costituzione diventa approvata; nessun agente può fare questo passo.
7. Dopo l'approvazione il documento è immutabile. Solo allora l'agente crea `tasks.yaml`, apre le
   fasi e comincia il primo task.
8. Controlla la mappa dei task in **Percorso** e premi **Approva il piano** in **Adesso**. Se
   `tasks.yaml` cambia dopo, le nuove attivazioni si bloccano e il tool chiede una riconferma.

Il cancello è applicato dal tool: senza Costituzione approvata non si attivano task, non si aprono
fasi e non si compongono prompt. I progetti nuovi richiedono inoltre `usage` e provenienza Git in
ogni report; se un runtime non espone i token, l’agente deve dichiararli non disponibili con il
motivo.

Un progetto senza Costituzione approvata non è pronto per l'implementazione.
