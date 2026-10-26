"""Oliver IA: rede neural MLP local para triagem demonstrativa.

O treinamento deste protótipo usa exemplos sintéticos. As saídas não são
previsões científicas nem alertas operacionais.

Os pesos treinados ficam salvos em ``pesos.json``. Na primeira execução as
redes são treinadas (alguns segundos) e o arquivo é criado; nas próximas o
servidor apenas carrega os pesos. Para treinar de novo, apague o arquivo ou
rode ``python -m oliver.neural``.
"""
import json
import math
import os
import random

RISK_NAMES = ('Baixo', 'Moderado', 'Alto')
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'pesos.json')


class MLP:
    def __init__(self, inputs, hidden=10, seed=7):
        self.inputs, self.hidden, self.outputs = inputs, hidden, 3
        rng = random.Random(seed)
        self.w1 = [[rng.uniform(-.45, .45) for _ in range(inputs)] for _ in range(hidden)]
        self.b1 = [0.0] * hidden
        self.w2 = [[rng.uniform(-.4, .4) for _ in range(hidden)] for _ in range(3)]
        self.b2 = [0.0] * 3

    def forward(self, x):
        h = [math.tanh(sum(w * v for w, v in zip(row, x)) + b) for row, b in zip(self.w1, self.b1)]
        z = [sum(w * v for w, v in zip(row, h)) + b for row, b in zip(self.w2, self.b2)]
        m = max(z)
        exp = [math.exp(v - m) for v in z]
        total = sum(exp)
        return h, [v / total for v in exp]

    def train(self, examples, epochs=42, lr=.075, seed=19):
        rng = random.Random(seed)
        order = list(range(len(examples)))
        for _ in range(epochs):
            rng.shuffle(order)
            for idx in order:
                x, label = examples[idx]
                h, p = self.forward(x)
                dz = [p[j] - (1.0 if j == label else 0.0) for j in range(3)]
                old_w2 = [row[:] for row in self.w2]
                for j in range(3):
                    for k in range(self.hidden):
                        self.w2[j][k] -= lr * dz[j] * h[k]
                    self.b2[j] -= lr * dz[j]
                for k in range(self.hidden):
                    dh = sum(dz[j] * old_w2[j][k] for j in range(3)) * (1 - h[k] * h[k])
                    for i in range(self.inputs):
                        self.w1[k][i] -= lr * dh * x[i]
                    self.b1[k] -= lr * dh

    def accuracy(self, examples):
        hits = sum(1 for x, y in examples if max(range(3), key=lambda i: self.forward(x)[1][i]) == y)
        return hits / len(examples)

    def predict(self, features):
        _, probabilities = self.forward(features)
        idx = max(range(3), key=lambda i: probabilities[i])
        score = round(100 * (probabilities[1] * .5 + probabilities[2]))
        return {
            'level': RISK_NAMES[idx],
            'score': score,
            'confidence': round(max(probabilities) * 100),
            'probabilities': {RISK_NAMES[i]: round(probabilities[i] * 100, 1) for i in range(3)},
        }

    def to_dict(self):
        return {'inputs': self.inputs, 'hidden': self.hidden, 'w1': self.w1, 'b1': self.b1, 'w2': self.w2, 'b2': self.b2}

    @classmethod
    def from_dict(cls, d):
        net = cls(d['inputs'], d['hidden'])
        net.w1, net.b1, net.w2, net.b2 = d['w1'], d['b1'], d['w2'], d['b2']
        return net


def synthetic_data(n=1400, seed=41):
    """Gera os exemplos sintéticos de treino dos dois módulos."""
    rng = random.Random(seed)
    fire, flood = [], []
    for _ in range(n):
        x = [rng.random() for _ in range(4)]
        s = .34 * x[0] + .30 * x[2] + .25 * (1 - x[1]) + .11 * x[3]
        fire.append((x, 0 if s < .40 else 1 if s < .67 else 2))
        z = [rng.random() for _ in range(5)]
        sf = .30 * z[0] + .25 * z[1] + .18 * z[2] + .17 * z[3] + .10 * z[4]
        flood.append((z, 0 if sf < .32 else 1 if sf < .60 else 2))
    return fire, flood


def train_networks():
    fire_data, flood_data = synthetic_data()
    fire = MLP(4, seed=7)
    fire.train(fire_data)
    flood = MLP(5, seed=31)
    flood.train(flood_data, seed=37)
    # Conjunto de teste separado (outra semente) para medir a acurácia.
    fire_test, flood_test = synthetic_data(n=600, seed=2024)
    metrics = {'fire_accuracy': round(fire.accuracy(fire_test), 4), 'flood_accuracy': round(flood.accuracy(flood_test), 4)}
    return fire, flood, metrics


class LocalNeuralAssistant:
    def __init__(self, weights_path=WEIGHTS_PATH):
        if os.path.exists(weights_path):
            with open(weights_path, encoding='utf-8') as f:
                data = json.load(f)
            self.fire = MLP.from_dict(data['fire'])
            self.flood = MLP.from_dict(data['flood'])
            self.metrics = data.get('metrics', {})
        else:
            self.fire, self.flood, self.metrics = train_networks()
            with open(weights_path, 'w', encoding='utf-8') as f:
                json.dump({'fire': self.fire.to_dict(), 'flood': self.flood.to_dict(), 'metrics': self.metrics}, f)

    def classify_fire(self, wind, humidity, dryness, slope):
        return self.fire.predict([wind / 100, humidity / 100, dryness / 100, slope / 100])

    def classify_flood(self, rainfall_24h, forecast_24h, distance_water_m, drainage, vulnerable_floor):
        return self.flood.predict([
            min(1.0, rainfall_24h / 200.0),
            min(1.0, forecast_24h / 200.0),
            max(0.0, 1.0 - distance_water_m / 5000.0),
            max(0.0, min(1.0, drainage)),
            max(0.0, min(1.0, vulnerable_floor)),
        ])


NEURAL_AI = LocalNeuralAssistant()


if __name__ == '__main__':
    # python -m oliver.neural  → treina de novo e mostra a acurácia no conjunto de teste
    if os.path.exists(WEIGHTS_PATH):
        os.remove(WEIGHTS_PATH)
    ai = LocalNeuralAssistant()
    print('Pesos salvos em', WEIGHTS_PATH)
    print('Acurácia no teste:', ai.metrics)
