import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/** Raiz da aplicação: só hospeda o outlet — a moldura visual é do `Shell`. */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  template: '<router-outlet />',
})
export class App {}
