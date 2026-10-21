# Primo prompt del progetto

## Prompt dell'utente

<!-- Incolla qui, senza riscriverlo, quello che vuoi ottenere. -->

## Addendum obbligatorio per l'agente

Questo addendum fa parte del primo prompt. L'agente lo esegue **prima** di creare task o scrivere
codice.

1. Leggi `agents/CONTRATTO.md`, `constitution.md`, `onboarding-findings.yaml` e questo file.
2. Non iniziare a implementare: stai compilando il progetto, non eseguendolo.
3. Tratta la sezione 0 della Costituzione come fotografia misurata, non come prosa da riassumere:
   distingui ciò che esiste davvero da ciò che la bozza immagina. Se bozza e repository
   contraddicono, mostra entrambe le cose e chiedi quale debba valere.
4. Fai domande all'utente, una o due per volta, prima sui gap `BLOCCANTE` e sulle contraddizioni;
   poi completa il catalogo in `onboarding-questions.md`, saltando soltanto ciò che è già stato
   dimostrato dalla repository o deciso in modo esplicito. Una risposta vaga non chiude una
   domanda.
5. Aggiorna `constitution.md` con le risposte. Le domande aperte restano scritte come aperte;
   non riempirle con ipotesi.
6. Il catalogo contiene circa 90 domande in 15 aree. Sono un massimo adattivo, non un questionario
   da scaricare tutto insieme: chiedi prima le risposte che cambiano architettura, perimetro o
   rischio; approfondisci i rami pertinenti; chiudi come `not_applicable` soltanto ciò che davvero
   non riguarda il progetto. Non eliminare domande dal file.
7. Prima di proporre l'approvazione, chiudi ogni voce bloccante, tecnica o di intervista, con una
   decisione esplicita:

   ```bash
   python3 /percorso/project-console/onboarding_findings.py \
     --workspace /percorso/progetto/.coord \
     --resolve PROD01 --status answered \
     --note "Decisione presa: ..."
   ```

   Per i gap tecnici usa `resolved`; per le domande usa `answered`. Usa `not_applicable` quando
   la voce non riguarda il progetto, `deferred` quando l'utente sceglie consapevolmente di
   rimandarla e `accepted_risk` solo quando accetta il rischio. Una nota vuota non è una decisione.
8. Dopo ogni chiusura, verifica che `onboarding-findings.yaml`, `onboarding-questions.md` e la
   sezione 0 di `constitution.md` siano stati rigenerati. Il console rifiuta l'approvazione se
   resta anche una sola voce bloccante aperta.
9. Quando la constitution è completa, proponi all'utente il piano finale: task, stack, skill,
   parallelismo, test e modalità. Lascia la constitution in `status: draft` e chiedi all'utente di
   controllarla e approvarla dalla pagina **Costituzione** del console.
10. Non scrivere mai `status: approved` e non approvare il documento al posto dell'utente. Solo
   dopo che la Costituzione risulta approvata dal front-end crea `tasks.yaml`, apri le fasi e
   inizia il primo task.
11. Il tool applica il cancello: prima dell'approvazione non può attivare task né comporre prompt.
   Non aggirarlo scrivendo direttamente i registri o un ordine.
12. Prima del primo task verifica di essere dentro un repository Git. Se non esiste, inizializzalo e
   crea un commit iniziale. Ogni consegna futura dichiarerà branch, worktree, commit iniziale,
   commit finale e path modificati.
13. Ogni report dichiara `usage`: token misurati se il runtime li espone, altrimenti
   `availability: unavailable` con il motivo. Non si scrive mai zero al posto di “non misurato”.
14. Dopo aver creato `tasks.yaml`, fermati: l'utente controlla la mappa in **Percorso** e la
    approva da **Adesso**. Non aprire le fasi e non attivare task prima di quella conferma; se il
    piano cambia, chiedi una nuova approvazione.

## Le 15 aree dell'intervista

1. Prodotto e risultato.
2. Persone, ruoli e carichi.
3. Percorsi operativi.
4. Perimetro e priorità.
5. Dati e modello del dominio.
6. Regole e cambi di stato.
7. Accesso, permessi e audit.
8. Privacy, sicurezza e dati sensibili.
9. Interfaccia, lingue e accessibilità.
10. Integrazioni e comunicazioni.
11. Qualità, test e criteri di accettazione.
12. Ambienti, pubblicazione e continuità.
13. Architettura e stack.
14. Piano, revisione e stop rule.
15. Verifica, consegna e governo.

Il testo completo, con gli identificatori da usare in `--resolve`, è in
`onboarding-questions.md`. Se una risposta apre un nuovo ramo, fai le relative domande di
approfondimento e riportale in sezione 12: il catalogo è il minimo, non un tetto.

### Regola per l'agente

Prima di dichiarare completa la bozza, rileggi le risposte e trasforma gli obiettivi vaghi in
conseguenze verificabili. Esempio: «gestire le campagne» non è un requisito; «un coordinatore crea
una campagna, assegna tre responsabili e vede lo stato dopo il ricaricamento» lo è. Se una risposta
resta ambigua, scrivi la domanda aperta in sezione 12 e non approvare.

### Regole di conversazione

- Spiega le scelte a una persona di 18 anni: cosa cambia in pratica, quali file tocca, cosa vede
  l'utente.
- Non usare sigle o termini tecnici senza una spiegazione.
- Non scegliere al posto dell'utente su stack, perimetro, ampiezza o rischi.
- Se una risposta manca, resta una domanda aperta; non inventare.
- Spiega ogni decisione come a una persona di 18 anni: cosa cambia in pratica, quali file tocca e
  cosa vedrà l'utente; niente tecnicismi senza traduzione.
- Il progetto può nascere da un foglio bianco: parti dalla repository scaricata e da questa
  cartella, non da un template implicito.
