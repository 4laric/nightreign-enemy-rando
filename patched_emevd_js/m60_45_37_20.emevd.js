// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1045370800, 15);
    RegisterBonfire(1045371950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1045371950, 1045370950);
    RegisterBonfire(1045371951, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1045371951, 1045370951);
    $InitializeCommonEvent(0, 90005580, 1045371952, 1045370952, 7660);
    $InitializeCommonEvent(0, 9005810, 1045370800, 1045370953, 1045371953, 5);
    $InitializeCommonEvent(0, 90015005, 1045371953, 1045370953, 1045370800);
    $InitializeCommonEvent(0, 90065901, 1045374890);
    $InitializeCommonEvent(0, 90005910, 1045371800, 7685);
    $InitializeCommonEvent(0, 91005505, 1045372500, 7685);
    $InitializeCommonEvent(0, 90015150, 1045370200, 73076);
    $InitializeCommonEvent(0, 90015151, 1045370200, 74036);
    $InitializeCommonEvent(0, 90015152, 1045370200, 74036);
    $InitializeCommonEvent(0, 90005201, 1045370210, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370211, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370212, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370213, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370214, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370219, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370220, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370228, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370229, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005201, 1045370231, 30010, 20010, 2, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015140, 1045371200, 200, 9110, 1045378200);
    $InitializeCommonEvent(0, 91005503, 1045371500);
    $InitializeCommonEvent(0, 91005503, 1045371511);
    $InitializeCommonEvent(0, 91005503, 1045371510);
    $InitializeCommonEvent(0, 90085612, 602, Hero.Revenant, 9247, 9227, 1045370280, 8462);
    if (1 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9237, 9227, 9227, 1045375280, 1045370281, 0, 0, 0, 20026);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9237, 9227, 9227, 1045375280, 1045370281, 1045370282, 0, 0, 20026);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9237, 9227, 9227, 1045375280, 1045370281, 1045370282, 1045370283, 0, 20026);
    }
    if (4 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9237, 9227, 9227, 1045375280, 1045370281, 1045370282, 1045370283, 1045370284, 20026);
    }
    $InitializeCommonEvent(0, 90085613, 602, 9237, 9227, 9227, 1045375280);
    $InitializeCommonEvent(0, 90085614, 602, 9237, 1045376280, 1045370280, 8462);
});

$Event(1045372800, Restart, function(chrEntityId) {
    EndIf(EventFlag(chrEntityId));
    WaitFor(CharacterHPValue(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    PlaySE(chrEntityId, SoundType.SFX, 888880000);
    WaitFor(CharacterDead(chrEntityId));
    HandleMinibossDefeat(chrEntityId);
    SetEventFlagID(chrEntityId, ON);
});
