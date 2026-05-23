// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015000, 0, 46620800, 903150600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46620800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 46620800, 30, 921010, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 46620800, 46620800, 1020, 921010, 11290, 903150600, 46620800);
    $InitializeCommonEvent(0, 9005810, 46620800, 46620500, 46621500, 5);
    $InitializeCommonEvent(0, 90015005, 46621500, 46622800, 46620800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 46620800, 921010, 46620800, 0, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 46620800);
    $InitializeCommonEvent(0, 90015016, 46620800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 46620800);
        $InitializeCommonEvent(0, 90015468, 46620800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90065111, 46620800, 46620810, 6001, 46620800);
    $InitializeCommonEvent(0, 90065112, 46620800, 46620810, 6001, 46620800);
    $InitializeCommonEvent(0, 90015199, 46620800);
    if (IsPlayMode(2)) {
        $InitializeCommonEvent(0, 90015040, 0);
    }
});

$Event(46622200, Default, function(chrEntityId) {
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
