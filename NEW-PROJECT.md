# Nuovo progetto — punto di partenza

Ogni progetto, anche un foglio bianco, parte da questa repository.

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
6. Solo dopo la tua conferma l'agente mette `status: approved`, crea `tasks.yaml`, apre le fasi e
   comincia il primo task.

Un progetto senza constitution approvata non è pronto per l'implementazione.
