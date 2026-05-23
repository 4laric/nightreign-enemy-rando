// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015000, 0, 46690800, 907100300, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46690800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 46690800, 30, 920210, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 46690800, 46690800, 1020, 920210, 11290, 907100300, 46690800);
    $InitializeCommonEvent(0, 9005810, 46690800, 46690500, 46691500, 5);
    $InitializeCommonEvent(0, 90015005, 46691500, 46692800, 46690800);
    GotoIf(S0, Signed(16951) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 46690800, 920210, 46690800, 16951, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 46690800);
    $InitializeCommonEvent(0, 90015016, 46690800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 46690800);
        $InitializeCommonEvent(0, 90015468, 46690800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015199, 46690800);
    if (IsPlayMode(2)) {
        $InitializeCommonEvent(0, 90015040, 0);
    }
});

$Event(46692200, Default, function(chrEntityId) {
    EndIf(
        !(!EventFlag(7603)
            && (InArea(chrEntityId, 1045392989)
                || InArea(chrEntityId, 1045392988)
                || InArea(chrEntityId, 1044362996)
                || InArea(chrEntityId, 1045382998)
                || InArea(chrEntityId, 1045382997)
                || InArea(chrEntityId, 1045362996)
                || InArea(chrEntityId, 1045362995)
                || InArea(chrEntityId, 1045362994))));
    DisableCharacter(chrEntityId);
    DisableCharacterCollision(chrEntityId);
});

$Event(46692500, Restart, function(chrEntityId, spEffectId, eventFlagId) {
    WaitFor(CharacterHasSpEffect(chrEntityId, spEffectId));
    SetEventFlagID(eventFlagId, ON);
});
