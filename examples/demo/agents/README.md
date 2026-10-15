# Gli agenti di questo progetto

Il coordinatore mostra il lavoro, non lo esegue: gli agenti sono chat separate (o sotto-agenti) a
cui si incolla un prompt. Questo file dice come si definiscono per un progetto nuovo.

## Cosa serve

1. **I registri** (`state.yaml`, `tasks.yaml`, ...): dove sta scritto cosa va fatto e a che punto e'.
2. **Il quaderno** (`PARALLEL-PROMPTS.md`): i prompt pronti, col codice di riconoscimento.
3. **I ruoli** (`agents/roles/*.md`): il testo che dice come lavora un agente. Quattro bastano e
   avanzano: chi coordina, chi analizza, chi esegue, chi verifica.
4. **La mappa degli agenti** (`agents.yaml`): quale ruolo, quale competenza, quale perimetro.

## La regola che tiene insieme il resto

Un agente prende la fase PRIMA di scrivere (una voce di claim in `state.yaml`), la rilascia quando
consegna, e non tocca i registri con una riscrittura libera: deposita una transizione. Senza questa
regola due corsie lavorano sugli stessi byte e nessuno se ne accorge.
