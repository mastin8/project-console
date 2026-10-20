# Primo prompt del progetto

## Prompt dell'utente

<!-- Incolla qui, senza riscriverlo, quello che vuoi ottenere. -->

## Addendum obbligatorio per l'agente

Questo addendum fa parte del primo prompt. L'agente lo esegue **prima** di creare task o scrivere
codice.

1. Leggi `agents/CONTRATTO.md`, `constitution.md` e questo file.
2. Non iniziare a implementare: stai compilando il progetto, non eseguendolo.
3. Fai domande all'utente, una o due per volta, su:
   - obiettivo e fuori perimetro;
   - stack tecnico e vincoli;
   - deliverable finale e criterio di “finito”;
   - numero e ampiezza dei task;
   - skill/competenze da usare e dove;
   - flusso normale/rigoroso, test e accettazione;
   - cosa può andare in parallelo e quali file sono condivisi;
   - rischi, migrazioni, sicurezza, release e stop rule.
4. Aggiorna `constitution.md` con le risposte. Le domande aperte restano scritte come aperte;
   non riempirle con ipotesi.
5. Quando la constitution è completa, proponi all'utente il piano finale: task, stack, skill,
   parallelismo, test e modalità. Aspetta la conferma.
6. Solo dopo la conferma scrivi `status: approved`, crea `tasks.yaml`, apre le fasi e inizia il
   primo task.

### Regole di conversazione

- Spiega le scelte a una persona di 18 anni: cosa cambia in pratica, quali file tocca, cosa vede
  l'utente.
- Non usare sigle o termini tecnici senza una spiegazione.
- Non scegliere al posto dell'utente su stack, perimetro, ampiezza o rischi.
- Se una risposta manca, resta una domanda aperta; non inventare.
- Il progetto può nascere da un foglio bianco: parti dalla repository scaricata e da questa
  cartella, non da un template implicito.
