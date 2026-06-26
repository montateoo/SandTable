
/*
  Designed for DIY MAchines Kinetic Sand Project and based on code originally written by Keith Lord 
  
You will need to install the WS2812FX library which can be found here: https://github.com/kitesurfer1404/WS2812FX

  LICENSE

  The MIT License (MIT)

  Portions Copyright (c) 2017  Keith Lord 

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
  THE SOFTWARE.
*/

#include <WS2812FX.h>

#define LED_PIN    6  // digital pin used to drive the LED strip
#define LED_COUNT 70  // number of LEDs on the strip - if you make a larger table with more LED's then adjust this number

int maximumBrightnesAllowed = 128;  // set this value the maximum brightness you want to allow the LEDs to reach (0 -> 255)
const byte interruptPin = 2;
const byte potBrightness = A0;
const byte potSpeed = A2;
int patternNumber = 10;  // preferred startup pattern
static unsigned long last_check_time = 0;

// for smoothing out the potentiometer readings

const int numReadings = 10;

int readingsBrightness[numReadings];      // the readings from the analog input
int readBrightnessIndex = 0;              // the index of the current reading
int totalBrightness = 0;                  // the running total
int averageBrightness = 0;
int inputBrightnessPin = A0;

WS2812FX tableSurfaceLEDs = WS2812FX(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// Ramps brightness 0 -> maximumBrightnesAllowed over rampMs, calling .service()
// at each step so the strip actually updates progressively instead of jumping
// straight to full brightness in one instant (spreads the current draw increase
// out over time instead of a single sharp step on the shared power supply).
void softStart(unsigned long rampMs) {
  const int steps = 30;
  for (int i = 1; i <= steps; i++) {
    int b = (maximumBrightnesAllowed * i) / steps;
    tableSurfaceLEDs.setBrightness(b);
    tableSurfaceLEDs.service();
    delay(rampMs / steps);
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(interruptPin, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(interruptPin), patternMode, FALLING);
  tableSurfaceLEDs.init();
  tableSurfaceLEDs.setBrightness(0);  // start dark -- softStart() ramps up below
  pattern10();
  softStart(1500);  // fade brightness 0 -> maximumBrightnesAllowed over 1.5s instead
                     // of snapping all 70 LEDs to full white in one instant, to avoid
                     // a sharp current step on the shared power supply at boot

    // initialize all the brightness readings to 50:
  for (int thisBrightnessReading = 0; thisBrightnessReading < numReadings; thisBrightnessReading++) {
    readingsBrightness[thisBrightnessReading] = 50;
  }
}


void patternMode() {
  
 static unsigned long last_interrupt_time = 0;
 unsigned long interrupt_time = millis();
 if (interrupt_time - last_interrupt_time > 400)    // If interrupts come faster than 400ms, assume it's a bounce and ignore
 {
  
  if (patternNumber == 10) {
    patternNumber = 0;
  }
  else {
  patternNumber = ++patternNumber;
  }
  //Serial.print("New pattern number");
  //Serial.println(patternNumber);
  applyPattern(patternNumber);

 }
 last_interrupt_time = interrupt_time;
}

// Shared by the button interrupt (above) and the PATTERN:<n> serial command
// (handleSerialCommand, below) so both go through the same dispatch.
void applyPattern(int n) {
  switch (n) {
    case 0:
    pattern0();
    break;
    case 1:
    pattern1();
    break;
    case 2:
    pattern2();
    break;
    case 3:
    pattern3();
    break;
    case 4:
    pattern4();
    break;
    case 5:
    pattern5();
    break;
    case 6:
    pattern6();
    break;
    case 7:
    pattern7();
    break;
    case 8:
    pattern8();
    break;
    case 9:
    pattern9();
    break;
    case 10:
    pattern10();
    break;
  }
}


void pattern0() {

  tableSurfaceLEDs .setMode(FX_MODE_CHASE_RAINBOW);
  tableSurfaceLEDs.setColor(WHITE);
  tableSurfaceLEDs.start();}

void pattern1() {

  tableSurfaceLEDs .setMode(FX_MODE_FADE);
  tableSurfaceLEDs.setColor(WHITE);
  tableSurfaceLEDs.start();}

void pattern2() {

  tableSurfaceLEDs .setMode(FX_MODE_COLOR_WIPE);
  tableSurfaceLEDs.setColor(WHITE);
  tableSurfaceLEDs.start();}


void pattern3() {

  tableSurfaceLEDs .setMode(FX_MODE_COLOR_WIPE_RANDOM);
  tableSurfaceLEDs.setColor(CYAN);
  tableSurfaceLEDs.start();}


  void pattern4() {
  tableSurfaceLEDs .setMode(FX_MODE_RAINBOW);
  tableSurfaceLEDs.setColor(RED);
  tableSurfaceLEDs.start();}

  
   void pattern5() {

  tableSurfaceLEDs .setMode(FX_MODE_RUNNING_LIGHTS);
  tableSurfaceLEDs.setColor(WHITE);
  tableSurfaceLEDs.start();}


     void pattern6() {

  tableSurfaceLEDs .setMode(FX_MODE_SPARKLE);
  tableSurfaceLEDs.setColor(WHITE);
  tableSurfaceLEDs.start();}

       void pattern7() {

  tableSurfaceLEDs .setMode(FX_MODE_COLOR_SWEEP_RANDOM);
  tableSurfaceLEDs.setColor(WHITE);
  tableSurfaceLEDs.start();}

         void pattern8() {

  tableSurfaceLEDs .setMode(FX_MODE_LARSON_SCANNER);
  tableSurfaceLEDs.setColor(RED);
  tableSurfaceLEDs.start();}

         void pattern9() {

  tableSurfaceLEDs .setMode(FX_MODE_FIRE_FLICKER_SOFT);
  tableSurfaceLEDs.setColor(ORANGE);
  tableSurfaceLEDs.start();}


           void pattern10() {

  tableSurfaceLEDs .setMode(FX_MODE_STATIC);
  tableSurfaceLEDs.setColor(WHITE);
  tableSurfaceLEDs.start();}

// Solid-color names used by the SOLID:<name> serial command (octoprint-nanoled's
// F1 race-flag mapping: RED/YELLOW/GREEN/WHITE). Unknown names fall back to WHITE.
uint32_t colorFromName(String name) {
  if (name == "RED") return RED;
  if (name == "YELLOW") return YELLOW;
  if (name == "GREEN") return GREEN;
  return WHITE;
}

// Line-based serial command parser, read from the Pi over the Nano's hardware
// UART (TX/RX wired to the Pi's GPIO UART, level-shifted on the Nano->Pi leg).
// Runs alongside the physical button/potentiometers -- a serial command simply
// overrides until the next button press or pot turn, neither side is disabled.
void handleSerialCommand() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd.startsWith("PATTERN:")) {
    patternNumber = cmd.substring(8).toInt();
    applyPattern(patternNumber);
  } else if (cmd.startsWith("SOLID:")) {
    tableSurfaceLEDs.setMode(FX_MODE_STATIC);
    tableSurfaceLEDs.setColor(colorFromName(cmd.substring(6)));
    tableSurfaceLEDs.start();
  } else if (cmd == "FLICKER_RAINBOW") {
    tableSurfaceLEDs.setMode(FX_MODE_MULTI_DYNAMIC);
    tableSurfaceLEDs.start();
  } else if (cmd == "FLASH_WHITE") {
    tableSurfaceLEDs.setMode(FX_MODE_STROBE);
    tableSurfaceLEDs.setColor(WHITE);
    tableSurfaceLEDs.start();
  }
}

void loop() {
  handleSerialCommand();
  tableSurfaceLEDs.service();

  unsigned long check_time = millis();
  
  if (check_time - last_check_time > 200){                              // If checks come faster than 300ms, assume it's a bounce and ignore


      // read the input on the potentiometer to determine the requested brightness for the LEDs
     
    totalBrightness = totalBrightness - readingsBrightness[readBrightnessIndex];  // subtract the last Brightness reading:
    readingsBrightness[readBrightnessIndex] = analogRead(inputBrightnessPin);     // read from the Brightness sensor:
    totalBrightness = totalBrightness + readingsBrightness[readBrightnessIndex];  // add the reading to the total:
    readBrightnessIndex = readBrightnessIndex + 1;                                // advance to the next position in the array:
  
    if (readBrightnessIndex >= numReadings) {                             // if we're at the end of the array...
      readBrightnessIndex = 0;                                            // ...wrap around to the beginning:
    }
  
    averageBrightness = totalBrightness / numReadings;                    // calculate the average:
    int ledValueBrightness = map(averageBrightness, -47, 900, 0, maximumBrightnesAllowed);    // Map the brightness value to range of LEDs 
    //Serial.print("Brightness of LEDs is set to ");
    //Serial.println(ledValueBrightness);
    tableSurfaceLEDs.setBrightness(ledValueBrightness);                 //set the table LEDs brightness value
    
    int potValueSpeed = analogRead(potSpeed);                           // read the input on analog pin 2 to determine the speed for the LED patterns
    long ledValueSpeed = map(potValueSpeed, 0, 1100, 0, 100000);         // read the input on the potentiometer to determine the requested speed for the LEDs
    //Serial.print("Speed of LED pattern set to ");
    //Serial.println(ledValueSpeed);
    tableSurfaceLEDs.setSpeed(ledValueSpeed);                           //set the table LEDs pattern speed
    
    last_check_time = check_time;
  }  
}
