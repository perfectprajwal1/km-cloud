import {Hook} from './Hook'; import {BigNum} from './BigNum'; import {Versus} from './Versus'; import {DateCard} from './DateCard';
import {Group} from './Group'; import {Place} from './Place'; import {Quote} from './Quote'; import {Points} from './Points';
import {Change} from './Change'; import {Next} from './Next'; import {Scale} from './Scale';
import {Engage} from './Engage';
export const CARDS: Record<string, React.FC> = {hook: Hook, bignum: BigNum, versus: Versus, date: DateCard, group: Group, place: Place,
  quote: Quote, points: Points, change: Change, next: Next, scale: Scale, engage: Engage};
