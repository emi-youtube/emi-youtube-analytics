import { Observable, defer, delay, of } from 'rxjs';

/** Faixa pedida no card: perto do que uma consulta agregada vai custar de verdade. */
const MINIMO_MS = 300;
const MAXIMO_MS = 800;

/**
 * Devolve o valor como a API devolveria: assíncrono e com atraso.
 *
 * Sem isso o mock responde no mesmo tick e os estados de carregamento nunca
 * aparecem — a tela pareceria pronta em desenvolvimento e piscaria em
 * produção. `defer` garante que o valor seja calculado (e o atraso sorteado)
 * na assinatura, não na montagem do Observable.
 */
export function comLatencia<T>(produzir: () => T): Observable<T> {
  return defer(() => {
    const espera = MINIMO_MS + Math.random() * (MAXIMO_MS - MINIMO_MS);
    return of(produzir()).pipe(delay(espera));
  });
}
