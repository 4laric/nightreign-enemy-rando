// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015000, 9060, 46780800, 902130002, 50, 0, 9061);
    $InitializeCommonEvent(0, 99055500, 46780800, 15);
    $InitializeCommonEvent(0, 90015030, 9060, 46780800, 50, 213021, 9061);
    $InitializeCommonEvent(0, 90015000, 9062, 46780800, 902130002, 50, 0, 9063);
    if (EventFlag(9999)) {
        $InitializeCommonEvent(0, 90035300, 46780200, 46780201, 9999);
    } else {
        if (IsPlayerNo(1)) {
            $InitializeCommonEvent(0, 90035300, 46780200, 46780201, 8085);
        }
        if (IsPlayerNo(2)) {
            $InitializeCommonEvent(0, 90035300, 46780200, 46780201, 8086);
        }
        if (IsPlayerNo(3)) {
            $InitializeCommonEvent(0, 90035300, 46780200, 46780201, 8087);
        }
    }
    $InitializeCommonEvent(0, 90015002, 8075, 46780200, 46780800, 46780800, 1020, 213001, 0, 0, 0);
    $InitializeCommonEvent(0, 90035050, 46780800, 46780200);
    $InitializeCommonEvent(0, 90035200, 46780800, 46780200, 8060, 200);
    $InitializeCommonEvent(0, 90035200, 46780800, 46780200, 8088, 500);
    $InitializeCommonEvent(0, 90035200, 46780800, 46780200, 8089, 800);
    $InitializeCommonEvent(0, 90035201, 46780200);
    $InitializeCommonEvent(0, 90035202, 46780800, 46780200);
    $InitializeCommonEvent(0, 90035203, 46780200);
    $InitializeCommonEvent(0, 90035204, 46780800, 46780200);
    $InitializeCommonEvent(0, 90035205, 46780800, 46780800, 46780200);
    $InitializeCommonEvent(0, 90035206, 46780800, 46780810, 46780200);
    $InitializeCommonEvent(0, 90035207, 46780800, 46780200);
    $InitializeCommonEvent(0, 90035208, 46780200, 46780201);
    $InitializeCommonEvent(0, 90035209, 46780200);
});

$Event(46782200, Restart, function() {
    WaitFor(CharacterHPValue(20000) <= 0);
    IssueShortWarpRequest(46780810, TargetEntityType.Character, 20000, 220);
    SetCharacterEventTarget(46780800, 46780810);
    WaitFor(CharacterHPValue(20000) != 0);
    RestartEvent();
});

$Event(46782500, Restart, function(chrEntityId, spEffectId, eventFlagId) {
    WaitFor(CharacterHasSpEffect(chrEntityId, spEffectId));
    SetEventFlagID(eventFlagId, ON);
});
