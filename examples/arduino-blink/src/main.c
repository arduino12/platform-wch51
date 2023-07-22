// Blink an LED connected to pin 1.7

#include <Arduino.h>

#define LED_PIN (17)

void setup()
{
  pinMode(LED_PIN, OUTPUT);
}

void loop()
{
  digitalWrite(LED_PIN, LOW);
  delay(1000);
  digitalWrite(LED_PIN, HIGH);
  delay(1000);
}
